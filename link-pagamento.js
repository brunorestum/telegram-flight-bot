'use strict';

/**
 * Link de pagamento do Pagar.me pelo bot do Telegram.
 *
 * Menu:     "💳 Link de pagamento" (botão do menu inicial) ou o comando abaixo
 * Comando:  /link Cliente; Itinerário; Valor; Parcelas
 * Exemplo:  /link Maria Silva; GRU-LIS / LIS-GRU; 8.580,00; 10
 *
 * Regras:
 *  - pode pedir: o ADMIN_ID, quem está em LINK_AUTORIZADOS e quem o admin aprovou por botão (aba "Autorizados" da planilha);
 *    quem não pode pede acesso pelo menu e o admin aprova ou recusa;
 *  - nada é criado sem o toque em "Criar link", e só quem pediu pode confirmar;
 *  - cartão de crédito, parcelas SEM JUROS, até o máximo que a pessoa informou; o link só pode ser pago 1 vez;
 *  - o nome do link é "Cliente - Itinerário" (o Pagar.me aceita até 64 caracteres);
 *  - a única chamada de escrita à API é POST /core/v5/paymentlinks. Nada de estorno, cancelamento ou alteração.
 *
 * Variáveis de ambiente (Render):
 *  PAGARME_API_KEY       chave secreta do Pagar.me (sk_...). Nunca no código.
 *  ADMIN_ID              id do Telegram de quem aprova acessos (padrão 695765510)
 *  LINK_AUTORIZADOS      ids do Telegram separados por vírgula (opcional; complementa a aba "Autorizados")
 *  LINK_NOTIFICAR        ids que recebem aviso de cada link criado (opcional)
 *  LINK_VALOR_MAXIMO     teto por link em reais (padrão 50000)
 *  LINK_PARCELAS_MAXIMO  teto de parcelas (padrão 12, máximo aceito pelo código 12)
 *  LINK_VALIDADE_DIAS    dias até o link expirar (padrão 7; 0 = não expira)
 */

const crypto = require('crypto');

const API_BASE = 'https://api.pagar.me/core/v5';
const TTL_MS = 10 * 60 * 1000; // pedido não confirmado em 10 minutos é descartado
const pendentes = new Map();
const pedidosAcesso = new Map(); // userId -> nome de quem pediu acesso e ainda não foi respondido
const aprovados = new Set();     // ids aprovados pelo admin (espelho da aba "Autorizados")
const PASSOS = ['link_cliente', 'link_itinerario', 'link_valor', 'link_parcelas'];
const ehPasso = (step) => PASSOS.includes(step);

// ---------------------------------------------------------------------------
// configuração
// ---------------------------------------------------------------------------

const lista = (s) => String(s || '').split(',').map((x) => x.trim()).filter(Boolean);

function config() {
  const dias = process.env.LINK_VALIDADE_DIAS;
  return {
    admin: String(process.env.ADMIN_ID || '695765510').trim(),
    autorizados: lista(process.env.LINK_AUTORIZADOS),
    notificar: lista(process.env.LINK_NOTIFICAR),
    valorMax: Number(process.env.LINK_VALOR_MAXIMO) || 50000,
    parcelasMax: Math.min(Number(process.env.LINK_PARCELAS_MAXIMO) || 12, 12),
    validadeDias: dias === undefined || dias === '' ? 7 : Math.max(0, Number(dias) || 0),
  };
}

// ---------------------------------------------------------------------------
// funções puras (testáveis sem rede)
// ---------------------------------------------------------------------------

/** "8.580,00" | "8580,5" | "8580.50" | "8580" -> centavos (inteiro) ou null */
function parseValor(txt) {
  let s = String(txt || '').replace(/R\$/gi, '').replace(/\s/g, '');
  if (!s) return null;
  if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.');
  else if (/^\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, '');
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return null;
  const centavos = Math.round(parseFloat(s) * 100);
  return centavos > 0 ? centavos : null;
}

/** Texto depois de "/link" -> { cliente, itinerario, valorCent, parcelas } ou { erro } */
function parseComando(texto, parcelasMax = 12) {
  const corpo = String(texto || '').replace(/^\/link(@\w+)?/i, '').trim();
  const partes = corpo.split(/;|\n/).map((p) => p.trim()).filter(Boolean);
  if (partes.length !== 4) {
    return { erro: 'Preciso de 4 informações separadas por ponto e vírgula: cliente; itinerário; valor; parcelas.' };
  }
  const [cliente, itinerario, valorTxt, parcelasTxt] = partes;
  const valorCent = parseValor(valorTxt);
  if (valorCent === null) return { erro: `Não entendi o valor "${valorTxt}". Exemplo: 8.580,00` };
  if (!/^\d+$/.test(parcelasTxt)) return { erro: `Parcelas deve ser um número inteiro (recebi "${parcelasTxt}").` };
  const parcelas = Number(parcelasTxt);
  if (parcelas < 1 || parcelas > parcelasMax) return { erro: `Parcelas deve ficar entre 1 e ${parcelasMax}.` };
  return { cliente, itinerario, valorCent, parcelas };
}

/** "Cliente - Itinerário", no máximo 64 caracteres (corta o itinerário primeiro, depois o cliente). */
function nomeDoLink(cliente, itinerario, max = 64) {
  const nome = `${cliente} - ${itinerario}`;
  if (nome.length <= max) return nome;
  const espaco = max - cliente.length - 3;
  if (espaco >= 8) return `${cliente} - ${itinerario.slice(0, espaco - 1)}…`;
  return `${cliente.slice(0, max - 12)}… - ${itinerario}`.slice(0, max);
}

const brl = (centavos) => (centavos / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

/** Corpo do POST /paymentlinks: cartão de crédito, parcelado sem juros até `parcelas`, pagável 1 vez. */
function montarPayload({ cliente, itinerario, valorCent, parcelas }, cfg) {
  const nome = nomeDoLink(cliente, itinerario);
  const payload = {
    name: nome,
    type: 'order',
    max_paid_sessions: 1,
    payment_settings: {
      accepted_payment_methods: ['credit_card'],
      credit_card_settings: {
        operation_type: 'auth_and_capture',
        installments_setup: {
          max_installments: parcelas,
          amount: valorCent,
          interest_type: 'simple',
          interest_rate: 0,
          free_installments: parcelas, // todas as parcelas sem juros
        },
      },
    },
    cart_settings: {
      items: [{ name: nome, description: `${cliente} | ${itinerario}`.slice(0, 250), amount: valorCent, default_quantity: 1 }],
    },
  };
  if (cfg.validadeDias > 0) payload.expires_in = cfg.validadeDias * 24 * 60; // minutos
  return payload;
}

// ---------------------------------------------------------------------------
// chamada à API (a única escrita: POST /paymentlinks)
// ---------------------------------------------------------------------------

async function criarLink(payload) {
  const chave = (process.env.PAGARME_API_KEY || '').trim();
  if (!chave) throw new Error('PAGARME_API_KEY não está configurada no servidor.');
  const axios = require('axios'); // carregado aqui para os testes das funções puras rodarem sem dependências
  const auth = Buffer.from(`${chave}:`).toString('base64');
  const r = await axios.post(`${API_BASE}/paymentlinks`, payload, {
    headers: { Authorization: `Basic ${auth}`, 'Content-Type': 'application/json', Accept: 'application/json' },
    timeout: 30000,
  });
  return { id: r.data.id, url: r.data.url, status: r.data.status };
}

function textoDoErro(e) {
  const d = e.response && e.response.data;
  const msg = d && (d.message || JSON.stringify(d.errors || d)) ? String(d.message || JSON.stringify(d.errors || d)) : e.message;
  return msg.slice(0, 300);
}

// ---------------------------------------------------------------------------
// integração com o bot
// ---------------------------------------------------------------------------

const quem = (from) => [from.first_name, from.last_name].filter(Boolean).join(' ') || from.username || String(from.id);
const autorizado = (id, cfg) => String(id) === cfg.admin || cfg.autorizados.includes(String(id)) || aprovados.has(String(id));

const USO = 'Use assim:\n/link Cliente; Itinerário; Valor; Parcelas\nExemplo:\n/link Maria Silva; GRU-LIS / LIS-GRU; 8.580,00; 10';
const PERGUNTAS = {
  link_cliente: '👤 Nome do cliente?\n(/restart cancela)',
  link_itinerario: '✈️ Itinerário?\nExemplo: GRU-LIS / LIS-GRU',
  link_valor: '💰 Valor do link?\nExemplo: 8.580,00',
  link_parcelas: (cfg) => `💳 Parcelas (máximo, sem juros)? De 1 a ${cfg.parcelasMax}.`,
};
const perguntar = (ctx, step, cfg) => ctx.reply(typeof PERGUNTAS[step] === 'function' ? PERGUNTAS[step](cfg) : PERGUNTAS[step]);

function limpaVencidos() {
  const agora = Date.now();
  for (const [k, v] of pendentes) if (agora - v.criadoEm > TTL_MS) pendentes.delete(k);
}

/**
 * hooks (opcionais, vêm do telegram_bot.js):
 *  getState(userId)                 estado do usuário no bot (para o passo 'link_aguardando_dados')
 *  carregarAutorizados()            -> Promise<string[]> ids aprovados guardados na planilha
 *  salvarAutorizado(id, nome)       -> Promise grava a aprovação na planilha
 */
function registrar(bot, hooks = {}) {
  const { Markup } = require('telegraf');

  const pronto = Promise.resolve()
    .then(() => (hooks.carregarAutorizados ? hooks.carregarAutorizados() : []))
    .then((ids) => ids.forEach((i) => aprovados.add(String(i))))
    .catch((e) => console.error('[link] não consegui ler a aba Autorizados:', e.message));

  // valida o pedido, guarda e mostra o resumo com os botões "Criar link / Cancelar"
  async function mostrarResumo(ctx, d, cfg) {
    if (d.valorCent / 100 > cfg.valorMax) {
      return ctx.reply(`O valor passa do limite de ${brl(cfg.valorMax * 100)} por link. Se for necessário, peça para aumentarem o limite.`);
    }
    limpaVencidos();
    const id = crypto.randomBytes(6).toString('hex');
    pendentes.set(id, { ...d, userId: ctx.from.id, nomeUsuario: quem(ctx.from), criadoEm: Date.now() });
    const nome = nomeDoLink(d.cliente, d.itinerario);
    const parcela = d.valorCent / d.parcelas;
    const resumo = [
      'Confira antes de criar o link:',
      `Nome do link: ${nome}`,
      `Cliente: ${d.cliente}`,
      `Itinerário: ${d.itinerario}`,
      `Valor: ${brl(d.valorCent)}`,
      `Pagamento: cartão de crédito, em até ${d.parcelas}x SEM juros (≈ ${brl(parcela)} por parcela)`,
      `O link só pode ser pago 1 vez${cfg.validadeDias > 0 ? ` e vale por ${cfg.validadeDias} dias` : ' e não expira'}.`,
      'Os juros do parcelamento ficam por conta da agência.',
    ].join('\n');
    return ctx.reply(resumo, Markup.inlineKeyboard([
      Markup.button.callback('✅ Criar link', `link_ok:${id}`),
      Markup.button.callback('❌ Cancelar', `link_no:${id}`),
    ]));
  }

  bot.command('meuid', (ctx) => ctx.reply(`Seu id no Telegram é ${ctx.from.id}`));

  bot.command('link', async (ctx) => {
    await pronto;
    const cfg = config();
    if (!autorizado(ctx.from.id, cfg)) {
      console.log(`[link] pedido negado para o id ${ctx.from.id}`);
      return ctx.reply('Você ainda não tem acesso a links de pagamento. Envie /start, toque em "💳 Link de pagamento" e peça acesso.');
    }
    const d = parseComando(ctx.message.text, cfg.parcelasMax);
    if (d.erro) return ctx.reply(`${d.erro}\n\n${USO}`);
    return mostrarResumo(ctx, d, cfg);
  });

  // Botão "Link de pagamento" do menu inicial
  bot.action('menu_link', async (ctx) => {
    await pronto;
    const cfg = config();
    const state = hooks.getState ? hooks.getState(ctx.from.id) : null;
    if (state && state.step !== 'waiting_pdf' && !ehPasso(state.step)) {
      return ctx.answerCbQuery('Termine o fluxo atual ou envie /restart.', { show_alert: true });
    }
    await ctx.answerCbQuery();
    if (autorizado(ctx.from.id, cfg)) {
      if (state) {
        state.link = {};
        state.step = 'link_cliente';
      }
      await ctx.reply('💳 Link de pagamento');
      return perguntar(ctx, 'link_cliente', cfg);
    }
    if (pedidosAcesso.has(String(ctx.from.id))) {
      return ctx.reply('⏳ Seu pedido de acesso já foi enviado ao Bruno. Assim que ele aprovar, eu aviso aqui.');
    }
    pedidosAcesso.set(String(ctx.from.id), quem(ctx.from));
    try {
      await ctx.telegram.sendMessage(
        cfg.admin,
        `🔐 ${quem(ctx.from)}${ctx.from.username ? ` (@${ctx.from.username})` : ''} quer acesso a links de pagamento. Aprovar?`,
        Markup.inlineKeyboard([
          Markup.button.callback('✅ Aprovar', `acesso_ok:${ctx.from.id}`),
          Markup.button.callback('❌ Recusar', `acesso_no:${ctx.from.id}`),
        ])
      );
      return ctx.reply('🔐 Você ainda não tem acesso a links de pagamento. Pedi autorização ao Bruno; eu aviso aqui quando ele responder.');
    } catch (e) {
      pedidosAcesso.delete(String(ctx.from.id));
      console.error('[link] não consegui avisar o admin:', e.message);
      return ctx.reply('Não consegui enviar o pedido de acesso agora. Tente de novo mais tarde.');
    }
  });

  // Aprovação / recusa: só o admin
  bot.action(/^acesso_(ok|no):(\d+)$/, async (ctx) => {
    const cfg = config();
    if (String(ctx.from.id) !== cfg.admin) return ctx.answerCbQuery('Só o administrador responde a esse pedido.', { show_alert: true });
    const [, decisao, alvo] = ctx.match;
    const nome = pedidosAcesso.get(alvo) || alvo;
    pedidosAcesso.delete(alvo);
    if (decisao === 'no') {
      await ctx.answerCbQuery('Recusado');
      await ctx.editMessageText(`❌ Acesso recusado para ${nome}.`);
      ctx.telegram.sendMessage(alvo, 'O Bruno não liberou o acesso a links de pagamento.').catch(() => {});
      return;
    }
    aprovados.add(alvo);
    let aviso = '';
    try {
      if (hooks.salvarAutorizado) await hooks.salvarAutorizado(alvo, nome);
    } catch (e) {
      console.error('[link] não consegui gravar a aprovação na planilha:', e.message);
      aviso = '\n⚠️ Não consegui gravar na aba "Autorizados"; vale até o bot reiniciar. Adicione o id na aba ou em LINK_AUTORIZADOS.';
    }
    await ctx.answerCbQuery('Aprovado');
    await ctx.editMessageText(`✅ Acesso liberado para ${nome} (id ${alvo}).${aviso}`);
    ctx.telegram.sendMessage(alvo, '✅ O Bruno liberou seu acesso! Envie /start e toque em "💳 Link de pagamento".').catch(() => {});
  });

  bot.action(/^link_no:(\w+)$/, async (ctx) => {
    const p = pendentes.get(ctx.match[1]);
    if (!p || p.userId !== ctx.from.id) return ctx.answerCbQuery('Esse pedido não é seu ou já venceu.', { show_alert: true });
    pendentes.delete(ctx.match[1]);
    await ctx.answerCbQuery('Cancelado');
    return ctx.editMessageText('❌ Pedido cancelado. Nenhum link foi criado.');
  });

  bot.action(/^link_ok:(\w+)$/, async (ctx) => {
    await pronto;
    const cfg = config();
    const id = ctx.match[1];
    const p = pendentes.get(id);
    if (!p || p.userId !== ctx.from.id || !autorizado(ctx.from.id, cfg)) {
      return ctx.answerCbQuery('Esse pedido não é seu ou já venceu.', { show_alert: true });
    }
    if (Date.now() - p.criadoEm > TTL_MS) {
      pendentes.delete(id);
      return ctx.editMessageText('⌛ O pedido venceu. Envie o /link de novo.');
    }
    pendentes.delete(id); // impede criar duas vezes com o mesmo pedido
    await ctx.answerCbQuery('Criando...');
    try {
      const link = await criarLink(montarPayload(p, cfg));
      console.log(JSON.stringify({ evento: 'link_criado', por: p.userId, cliente: p.cliente, itinerario: p.itinerario, valor: p.valorCent / 100, parcelas: p.parcelas, link_id: link.id }));
      await ctx.editMessageText(`✅ Link criado:\n${link.url}\n\n${nomeDoLink(p.cliente, p.itinerario)}\n${brl(p.valorCent)} em até ${p.parcelas}x sem juros`);
      for (const destino of cfg.notificar.filter((x) => x !== String(ctx.from.id))) {
        ctx.telegram.sendMessage(destino, `Link criado por ${p.nomeUsuario}:\n${nomeDoLink(p.cliente, p.itinerario)}\n${brl(p.valorCent)} em até ${p.parcelas}x sem juros\n${link.url}`).catch(() => {});
      }
    } catch (e) {
      console.error('[link] erro ao criar:', textoDoErro(e));
      await ctx.editMessageText(`Não consegui criar o link: ${textoDoErro(e)}\nNada foi cobrado. Envie o /link de novo quando corrigir.`);
    }
  });

  // Uma resposta por pergunta: cliente, itinerário, valor, parcelas
  async function receberDados(ctx, state) {
    await pronto;
    const cfg = config();
    if (!autorizado(ctx.from.id, cfg)) {
      state.step = 'waiting_pdf';
      return ctx.reply('Você não tem acesso a links de pagamento.');
    }
    const txt = ctx.message.text.trim();
    const l = (state.link = state.link || {});
    if (state.step === 'link_cliente') {
      l.cliente = txt;
      state.step = 'link_itinerario';
    } else if (state.step === 'link_itinerario') {
      l.itinerario = txt;
      state.step = 'link_valor';
    } else if (state.step === 'link_valor') {
      const v = parseValor(txt);
      if (v === null) return ctx.reply(`Não entendi o valor "${txt}". Exemplo: 8.580,00`);
      if (v / 100 > cfg.valorMax) return ctx.reply(`O valor passa do limite de ${brl(cfg.valorMax * 100)} por link. Envie outro valor.`);
      l.valorCent = v;
      state.step = 'link_parcelas';
    } else {
      if (!/^\d+$/.test(txt) || Number(txt) < 1 || Number(txt) > cfg.parcelasMax) {
        return ctx.reply(`Envie um número de 1 a ${cfg.parcelasMax}.`);
      }
      const d = { cliente: l.cliente, itinerario: l.itinerario, valorCent: l.valorCent, parcelas: Number(txt) };
      state.step = 'waiting_pdf';
      state.link = {};
      return mostrarResumo(ctx, d, cfg);
    }
    return perguntar(ctx, state.step, cfg);
  }
  return { receberDados, ehPasso };
}

module.exports = { registrar, autorizado, parseValor, parseComando, nomeDoLink, montarPayload, config };
