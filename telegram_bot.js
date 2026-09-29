#!/usr/bin/env node

/**
 * Bot Telegram para Automação de Vendas de Voos
 * PDF -> dados do voo (parser direto, IA como plano B, ou manual)
 * -> confirmação -> dados da venda -> 1 linha por passageiro no Google Sheets
 */

const { Telegraf, Markup } = require('telegraf');
const axios = require('axios');
const pdfParse = require('pdf-parse');
const { google } = require('googleapis');
const { parseFlightText } = require('./flightParser');
require('dotenv').config();

// ============================================================================
// CONFIGURAÇÕES
// ============================================================================

const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const FREELLMAPI_URL = process.env.FREELLMAPI_URL || 'http://localhost:3002';
const FREELLMAPI_KEY = process.env.FREELLMAPI_KEY;
const GOOGLE_SHEET_ID = process.env.GOOGLE_SHEET_ID;
const GOOGLE_SHEET_NAME = process.env.GOOGLE_SHEET_NAME || 'Vendas';
const COMISSAO = (Number(process.env.COMISSAO_PERCENT) || 20) / 100;

if (!BOT_TOKEN) {
  console.error('❌ TELEGRAM_BOT_TOKEN não configurado!');
  process.exit(1);
}

const bot = new Telegraf(BOT_TOKEN);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ============================================================================
// ESTADO DO USUÁRIO (em memória)
// ============================================================================

const userState = new Map();

function initUserState(userId) {
  if (!userState.has(userId)) {
    userState.set(userId, {
      step: 'waiting_pdf',
      flightData: {},
      warnings: [],
      shared: {},
      passengers: [],
      paxIndex: 0,
      paxData: [],
      current: {},
      editIndex: 0
    });
  }
  return userState.get(userId);
}

// ============================================================================
// EXTRAÇÃO DOS DADOS DO VOO
// ============================================================================

const AI_SYSTEM_PROMPT = `Você é um extrator de dados de passagens aéreas. Extraia do texto os dados abaixo e responda SOMENTE com JSON:
{
  "data_ida": "DD/MM/YYYY (data da primeira decolagem)",
  "horario_ida": "HH:MM (horário da primeira decolagem)",
  "itinerario_ida": "códigos IATA de todos os trechos em sequência (ex: GRU-GIG ou SDU-CGH-REC-FEN)",
  "data_volta": "DD/MM/YYYY ou null se só ida",
  "horario_volta": "HH:MM ou null",
  "itinerario_volta": "códigos IATA em sequência ou null",
  "cia_aerea": "nome da companhia",
  "localizador": "código da reserva (6 caracteres)",
  "passageiros": ["NOME 1", "NOME 2"]
}
Regras: use null para o que não estiver no texto. NUNCA invente valores. Sem explicações, sem markdown.`;

async function extractWithAI(pdfText) {
  let lastErr;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const response = await axios.post(
        `${FREELLMAPI_URL}/v1/chat/completions`,
        {
          model: 'auto',
          messages: [
            { role: 'system', content: AI_SYSTEM_PROMPT },
            { role: 'user', content: `Texto do PDF:\n\n${pdfText.slice(0, 8000)}` }
          ],
          temperature: 0,
          max_tokens: 900
        },
        {
          headers: { Authorization: `Bearer ${FREELLMAPI_KEY}` },
          timeout: 60000
        }
      );

      const content = response.data.choices[0].message.content.trim();
      // A IA às vezes coloca texto ou ``` em volta do JSON: pega só o trecho {...}
      const match = content.match(/\{[\s\S]*\}/);
      if (!match) throw new Error('A IA não retornou JSON: ' + content.slice(0, 150));

      const data = JSON.parse(match[0]);
      for (const k of Object.keys(data)) {
        if (data[k] === 'null' || data[k] === '') data[k] = null;
      }
      if (!Array.isArray(data.passageiros)) {
        data.passageiros = data.passageiros ? [String(data.passageiros)] : [];
      }
      return data;
    } catch (err) {
      lastErr = err;
      const body = err.response && err.response.data
        ? JSON.stringify(err.response.data).slice(0, 300)
        : '';
      console.error(`⚠️ IA - tentativa ${attempt}/3 falhou: ${err.message} ${body}`);
      if (attempt < 3) await sleep(2000 * attempt);
    }
  }
  throw lastErr;
}

// Confere se o que a IA devolveu realmente aparece no texto do PDF
function checkAgainstText(data, pdfText) {
  const warnings = [];
  const text = pdfText.toUpperCase();
  if (data.localizador && !text.includes(String(data.localizador).toUpperCase())) {
    warnings.push('Localizador não encontrado no texto do PDF');
  }
  for (const k of ['horario_ida', 'horario_volta']) {
    if (data[k] && !pdfText.includes(data[k])) {
      warnings.push(`${k.replace('_', ' ')} (${data[k]}) não encontrado no texto do PDF`);
    }
  }
  return warnings;
}

// Retorna { data, warnings, via } ou { data: null, reason }
async function extractFlightDataFromPDF(pdfBuffer) {
  const parsedPdf = await pdfParse(pdfBuffer);
  const pdfText = (parsedPdf.text || '').trim();

  // PDF sem texto = imagem/escaneado: não adianta mandar para a IA
  if (pdfText.length < 40) {
    return { data: null, reason: 'sem_texto' };
  }

  // 1º: parser direto (sem IA)
  const parsed = parseFlightText(pdfText);
  if (parsed) {
    console.log('✅ PDF lido pelo parser direto:', parsed.localizador);
    return { data: parsed, warnings: parsed.avisos || [], via: 'parser' };
  }

  // 2º: IA como plano B (só se configurada; na nuvem normalmente não há)
  if (!FREELLMAPI_KEY) {
    console.log('📄 Padrão não reconhecido e IA não configurada → modo manual');
    return { data: null, reason: 'ia_falhou' };
  }
  console.log('📄 Padrão não reconhecido, enviando para FreeLLMAPI...');
  try {
    const data = await extractWithAI(pdfText);
    return { data, warnings: checkAgainstText(data, pdfText), via: 'ia' };
  } catch (err) {
    console.error('❌ IA falhou nas 3 tentativas:', err.message);
    return { data: null, reason: 'ia_falhou' };
  }
}

// ============================================================================
// CONFIRMAÇÃO / CORREÇÃO MANUAL DOS DADOS DO VOO
// ============================================================================

const editFields = [
  { key: 'data_ida', label: '📅 Data da ida (DD/MM/AAAA)' },
  { key: 'horario_ida', label: '🕐 Horário da ida (HH:MM)' },
  { key: 'itinerario_ida', label: '🛫 Itinerário da ida (ex: SDU-CGH-REC-FEN)' },
  { key: 'data_volta', label: '📅 Data da volta (DD/MM/AAAA)' },
  { key: 'horario_volta', label: '🕐 Horário da volta (HH:MM)' },
  { key: 'itinerario_volta', label: '🛬 Itinerário da volta' },
  { key: 'cia_aerea', label: '✈️ Cia aérea' },
  { key: 'localizador', label: '🎫 Localizador' },
  { key: 'passageiros', label: '👥 Passageiros (separados por vírgula)' }
];

function showValue(v) {
  if (Array.isArray(v)) return v.join(', ') || '?';
  return v || '?';
}

function sendConfirmation(ctx, state) {
  const f = state.flightData;
  let text = `
✈️ Dados do voo:

📅 Data ida: ${showValue(f.data_ida)}
🕐 Horário ida: ${showValue(f.horario_ida)}
🛫 Itinerário ida: ${showValue(f.itinerario_ida)}

📅 Data volta: ${showValue(f.data_volta)}
🕐 Horário volta: ${showValue(f.horario_volta)}
🛬 Itinerário volta: ${showValue(f.itinerario_volta)}

✈️ Cia aérea: ${showValue(f.cia_aerea)}
🎫 Localizador: ${showValue(f.localizador)}
👥 Passageiros: ${showValue(f.passageiros)}
`.trim();

  if (state.warnings && state.warnings.length) {
    text += '\n\n⚠️ Confira com atenção:\n' + state.warnings.map((w) => `• ${w}`).join('\n');
  }
  text += '\n\nEstá correto?';

  state.step = 'waiting_confirmation';
  ctx.reply(
    text,
    Markup.inlineKeyboard([
      [
        Markup.button.callback('✅ Correto', 'flight_ok'),
        Markup.button.callback('✏️ Corrigir', 'flight_edit')
      ]
    ])
  );
}

function askEditField(ctx, state) {
  const field = editFields[state.editIndex];
  const cur = state.flightData[field.key];
  const curTxt = Array.isArray(cur) ? cur.join(', ') : cur;
  ctx.reply(
    `${field.label}\nAtual: ${curTxt || '(vazio)'}\n\n` +
    `Envie o valor certo, "." para manter, ou "-" para deixar vazio.`
  );
}

function startEditing(ctx, state) {
  state.editIndex = 0;
  state.step = 'editing';
  askEditField(ctx, state);
}

// ============================================================================
// GOOGLE SHEETS
// ============================================================================

// Converte "1250", "1.250,50", "R$ 1.250,50" em número
function toNumber(v) {
  if (typeof v === 'number') return v;
  let s = String(v == null ? '' : v).replace(/R\$/gi, '').replace(/\s/g, '');
  if (s.includes(',')) {
    s = s.replace(/\./g, '').replace(',', '.');
  } else if (/^\d{1,3}(\.\d{3})+$/.test(s)) {
    s = s.replace(/\./g, '');
  }
  const n = parseFloat(s);
  return Number.isNaN(n) ? NaN : n;
}

// Monta os valores por NOME de coluna. Assim a ordem das colunas na planilha
// pode mudar (ou ganhar colunas novas) sem quebrar o bot.
function buildRow(data, today) {
  const tz = { timeZone: 'America/Sao_Paulo' };
  const dataSale = today.toLocaleDateString('pt-BR', tz); // ex: 28/09/2026
  const month = Number(today.toLocaleDateString('pt-BR', { ...tz, month: 'numeric' })); // ex: 9
  const lucro = toNumber(data.lucro) || 0; // lucro bruto informado
  const comissao = Math.round(lucro * COMISSAO * 100) / 100;
  const dash = (v) => (v ? v : '-'); // na planilha, "sem volta" = "-"
  // CPF só com dígitos: apóstrofo mantém o zero à esquerda
  const cpf = /^\d+$/.test(String(data.cpf || '')) ? `'${data.cpf}` : data.cpf || '';

  return {
    'data de venda': dataSale,
    mes: month,
    conta: data.conta || '',
    'data da ida': data.data_ida || '',
    'horario da ida': data.horario_ida || '',
    'itinerario da ida': data.itinerario_ida || '',
    'data da volta': dash(data.data_volta),
    'horario da volta': dash(data.horario_volta),
    'itinerario da volta': dash(data.itinerario_volta),
    'cia aerea': data.cia_aerea || '',
    localizador: data.localizador || '',
    cpf,
    nome: data.nome || '',
    valor: toNumber(data.valor) || 0,
    lucro, // lucro informado (o "Base do imposto" é fórmula da planilha, não é escrito aqui)
    'lucro na operacao': lucro, // nome antigo da mesma coluna
    obs: data.obs || '',
    vendedor: data.vendedor || '',
    comissao,
    pagamento: data.pagamento || ''
    // "Base do imposto", "Lucro não tributado", parcelas etc. ficam em branco
  };
}

const norm = (h) =>
  String(h || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();

function colLetter(n) {
  let s = '';
  while (n > 0) {
    const r = (n - 1) % 26;
    s = String.fromCharCode(65 + r) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

// Recebe uma LISTA de vendas (1 por passageiro) e adiciona todas de uma vez
async function fillGoogleSheet(list) {
  try {
    const auth = new google.auth.GoogleAuth({
      ...(process.env.GOOGLE_CREDENTIALS_JSON
        ? { credentials: JSON.parse(process.env.GOOGLE_CREDENTIALS_JSON) }
        : { keyFile: process.env.GOOGLE_CREDENTIALS_FILE || './google-credentials.json' }),
      scopes: ['https://www.googleapis.com/auth/spreadsheets']
    });
    const sheets = google.sheets({ version: 'v4', auth });

    const today = new Date();
    // A aba tem tabelas de resumo logo abaixo dos dados: em vez de "append"
    // (que poderia escrever por cima), inserimos linhas novas depois da
    // última venda e gravamos nelas.
    const meta = await sheets.spreadsheets.get({
      spreadsheetId: GOOGLE_SHEET_ID,
      fields: 'sheets.properties(sheetId,title)'
    });
    const aba = meta.data.sheets.find((x) => x.properties.title === GOOGLE_SHEET_NAME);
    if (!aba) throw new Error(`Aba "${GOOGLE_SHEET_NAME}" não encontrada na planilha`);
    const sheetId = aba.properties.sheetId;

    const colA = await sheets.spreadsheets.values.get({
      spreadsheetId: GOOGLE_SHEET_ID,
      range: `${GOOGLE_SHEET_NAME}!A:A`
    });
    const a = (colA.data.values || []).map((r) => (r[0] || '').toString().trim());
    let header = a.findIndex((v) => v.toLowerCase() === 'data de venda');
    if (header < 0) throw new Error('Cabeçalho "Data de venda" não encontrado na coluna A');
    let last = header; // índice (base 0) da última linha de dados
    while (last + 1 < a.length && a[last + 1] !== '') last += 1;
    const firstNew = last + 1; // índice base 0 da primeira linha nova

    // Cabeçalho real da planilha: cada valor vai na coluna de mesmo nome
    const hdr = await sheets.spreadsheets.values.get({
      spreadsheetId: GOOGLE_SHEET_ID,
      range: `${GOOGLE_SHEET_NAME}!${header + 1}:${header + 1}`
    });
    const cols = ((hdr.data.values || [[]])[0] || []).map(norm);
    const values = list.map((d) => {
      const m = buildRow(d, today);
      return cols.map((c) => (c in m ? m[c] : ''));
    });
    const lastCol = colLetter(cols.length);
    const faltando = ['data de venda', 'nome', 'comissao'].filter((c) => !cols.includes(c));
    if (faltando.length) throw new Error('Colunas não encontradas no cabeçalho: ' + faltando.join(', '));

    await sheets.spreadsheets.batchUpdate({
      spreadsheetId: GOOGLE_SHEET_ID,
      resource: {
        requests: [
          {
            insertDimension: {
              range: { sheetId, dimension: 'ROWS', startIndex: firstNew, endIndex: firstNew + values.length },
              inheritFromBefore: true
            }
          }
        ]
      }
    });

    await sheets.spreadsheets.values.update({
      spreadsheetId: GOOGLE_SHEET_ID,
      range: `${GOOGLE_SHEET_NAME}!A${firstNew + 1}:${lastCol}${firstNew + values.length}`,
      valueInputOption: 'USER_ENTERED',
      resource: { values }
    });

    // "Base do imposto" é fórmula: copia a fórmula da última venda para as linhas novas
    const cBase = cols.indexOf('base do imposto');
    if (cBase >= 0 && last > header) {
      await sheets.spreadsheets.batchUpdate({
        spreadsheetId: GOOGLE_SHEET_ID,
        resource: {
          requests: [
            {
              copyPaste: {
                source: {
                  sheetId,
                  startRowIndex: last,
                  endRowIndex: last + 1,
                  startColumnIndex: cBase,
                  endColumnIndex: cBase + 1
                },
                destination: {
                  sheetId,
                  startRowIndex: firstNew,
                  endRowIndex: firstNew + values.length,
                  startColumnIndex: cBase,
                  endColumnIndex: cBase + 1
                },
                pasteType: 'PASTE_FORMULA'
              }
            }
          ]
        }
      });
    }

    return true;
  } catch (error) {
    console.error('❌ Erro ao preencher Google Sheets:', error.message);
    throw error;
  }
}

// ============================================================================
// FLUXO DO BOT
// ============================================================================

bot.start((ctx) => {
  userState.delete(ctx.from.id);
  initUserState(ctx.from.id);
  ctx.reply(
    `👋 Olá! Sou um bot para automação de vendas de voos.\n\n` +
    `📄 Envie um PDF da passagem aérea para começar!\n` +
    `Se eu não conseguir ler o PDF, você pode preencher os dados manualmente.`
  );
});

// PDF recebido
bot.on('document', async (ctx) => {
  const userId = ctx.from.id;
  const state = initUserState(userId);

  try {
    if (state.step !== 'waiting_pdf') {
      ctx.reply('⏳ Termine o fluxo atual ou envie /restart para recomeçar.');
      return;
    }

    const doc = ctx.message.document;
    const isPdf = doc.mime_type === 'application/pdf' ||
      (doc.file_name || '').toLowerCase().endsWith('.pdf');
    if (!isPdf) {
      ctx.reply('📄 Envie o arquivo em PDF, ou /manual para preencher os dados na mão.');
      return;
    }

    ctx.reply('📥 Recebendo PDF...');

    const file = await ctx.telegram.getFile(doc.file_id);
    const fileUrl = `https://api.telegram.org/file/bot${BOT_TOKEN}/${file.file_path}`;
    const response = await axios.get(fileUrl, { responseType: 'arraybuffer' });
    const pdfBuffer = Buffer.from(response.data);

    ctx.reply('🤖 Extraindo dados do PDF...');
    const result = await extractFlightDataFromPDF(pdfBuffer);

    if (!result.data) {
      const motivo = result.reason === 'sem_texto'
        ? 'Esse PDF parece ser uma imagem (sem texto para eu ler).'
        : 'Não consegui interpretar esse PDF.';
      ctx.reply(`⚠️ ${motivo}\n\nVamos preencher os dados do voo manualmente. (/restart cancela)`);
      state.flightData = {};
      state.warnings = [];
      startEditing(ctx, state);
      return;
    }

    state.flightData = result.data;
    state.warnings = result.warnings || [];
    sendConfirmation(ctx, state);
  } catch (error) {
    console.error('❌ Erro no processamento do PDF:', error.message);
    ctx.reply(`❌ Erro: ${error.message}\n\nEnvie outro PDF, ou /manual para preencher na mão.`);
    state.step = 'waiting_pdf';
  }
});

// Foto / print em vez de PDF
bot.on('photo', (ctx) => {
  const state = initUserState(ctx.from.id);
  if (state.step !== 'waiting_pdf') return;
  ctx.reply(
    '🖼️ Ainda não leio imagens. Envie o PDF da reserva, ' +
    'ou use /manual para preencher os dados do voo na mão.'
  );
});

// Entrada manual dos dados do voo
bot.command('manual', (ctx) => {
  const state = initUserState(ctx.from.id);
  if (state.step !== 'waiting_pdf') {
    ctx.reply('⏳ Termine o fluxo atual ou envie /restart para recomeçar.');
    return;
  }
  state.flightData = {};
  state.warnings = [];
  startEditing(ctx, state);
});

// Confirmação dos dados do voo
bot.action('flight_ok', async (ctx) => {
  const state = initUserState(ctx.from.id);
  await ctx.answerCbQuery();
  if (state.step !== 'waiting_confirmation') return;

  const pax = state.flightData.passageiros || [];
  state.passengers = pax.length ? pax : [null]; // sem nomes: pergunta o nome
  state.paxIndex = 0;
  state.paxData = [];
  state.shared = {};
  state.current = {};

  state.step = 'asking_account';
  ctx.reply('💼 Qual é a conta?');
});

bot.action('flight_edit', async (ctx) => {
  const state = initUserState(ctx.from.id);
  await ctx.answerCbQuery();
  if (state.step !== 'waiting_confirmation') return;
  startEditing(ctx, state);
});

// Perguntadas UMA vez (valem para todos os passageiros)
const sharedFlow = [
  { step: 'asking_account', field: 'conta', prompt: '💼 Qual é a conta?' },
  { step: 'asking_vendedor', field: 'vendedor', prompt: '👨‍💼 Vendedor?' },
  { step: 'asking_pagamento', field: 'pagamento', prompt: '💳 Forma de pagamento?' },
  { step: 'asking_obs', field: 'obs', prompt: '📌 Observações (ou /skip)?' }
];

// Perguntadas para CADA passageiro (1 linha na planilha por passageiro)
function startPassenger(ctx, state) {
  const total = state.passengers.length;
  const nome = state.passengers[state.paxIndex];
  state.current = {};
  if (nome) {
    state.current.nome = nome;
    state.step = 'pax_cpf';
    ctx.reply(`👤 Passageiro ${state.paxIndex + 1}/${total}: ${nome}\n\n🪪 CPF?`);
  } else {
    state.step = 'pax_nome';
    ctx.reply(`👤 Passageiro ${state.paxIndex + 1}/${total}\n\n📝 Nome?`);
  }
}

bot.on('text', async (ctx) => {
  const userId = ctx.from.id;
  const state = initUserState(userId);
  const text = ctx.message.text.trim();

  if (text === '/restart') {
    userState.delete(userId);
    initUserState(userId);
    ctx.reply('🔄 Reiniciado! Envie um PDF (ou /manual).');
    return;
  }

  // Tentar salvar de novo depois de um erro no Sheets
  if (text === '/retry') {
    if (state.step === 'waiting_retry') {
      await finalizeSale(ctx, userId, state);
    } else {
      ctx.reply('Não há nada para tentar de novo agora.');
    }
    return;
  }

  // Correção / preenchimento manual dos dados do voo
  if (state.step === 'editing') {
    const field = editFields[state.editIndex];
    if (text !== '.') {
      if (text === '-') {
        state.flightData[field.key] = field.key === 'passageiros' ? [] : null;
      } else if (field.key === 'passageiros') {
        state.flightData.passageiros = text.split(/[,;\n]/).map((s) => s.trim()).filter(Boolean);
      } else {
        state.flightData[field.key] = text;
      }
    }
    state.editIndex += 1;
    if (state.editIndex < editFields.length) {
      askEditField(ctx, state);
    } else {
      state.warnings = [];
      sendConfirmation(ctx, state);
    }
    return;
  }

  // Perguntas compartilhadas
  const si = sharedFlow.findIndex((d) => d.step === state.step);
  if (si >= 0) {
    state.shared[sharedFlow[si].field] = text === '/skip' ? '' : text;
    if (si < sharedFlow.length - 1) {
      state.step = sharedFlow[si + 1].step;
      ctx.reply(sharedFlow[si + 1].prompt);
    } else {
      startPassenger(ctx, state);
    }
    return;
  }

  // Perguntas por passageiro
  if (state.step === 'pax_nome') {
    state.current.nome = text;
    state.step = 'pax_cpf';
    ctx.reply('🪪 CPF?');
    return;
  }
  if (state.step === 'pax_cpf') {
    state.current.cpf = text;
    state.paxData.push(state.current);
    state.paxIndex += 1;
    if (state.paxIndex < state.passengers.length) {
      startPassenger(ctx, state);
    } else {
      state.step = 'res_valor';
      ctx.reply('💰 Valor total da reserva?');
    }
    return;
  }
  // Valor e lucro: UMA vez por reserva (vão na 1ª linha; as demais ficam com 0)
  if (state.step === 'res_valor' || state.step === 'res_lucro') {
    const n = toNumber(text);
    if (Number.isNaN(n)) {
      ctx.reply('⚠️ Não entendi esse número. Ex: 1250 ou 1.250,50');
      return;
    }
    if (state.step === 'res_valor') {
      state.shared.valor = n;
      state.step = 'res_lucro';
      ctx.reply('📈 Lucro na operação (total da reserva)?');
      return;
    }
    state.shared.lucro = n;
    await finalizeSale(ctx, userId, state);
    return;
  }

  if (state.step === 'waiting_pdf') {
    ctx.reply('📄 Envie um PDF da passagem aérea (ou /manual para preencher na mão).');
  } else if (state.step === 'waiting_confirmation') {
    ctx.reply('👆 Use os botões acima para confirmar ou corrigir os dados do voo.');
  } else if (state.step === 'waiting_retry') {
    ctx.reply('Envie /retry para tentar salvar de novo, ou /restart para recomeçar.');
  }
});

async function finalizeSale(ctx, userId, state) {
  try {
    ctx.reply('💾 Preenchendo Google Sheets...');

    const rows = state.paxData.map((pax, i) => ({
      ...state.flightData,
      ...state.shared,
      ...pax,
      // valor/lucro só na 1ª linha da reserva; demais passageiros = 0
      valor: i === 0 ? state.shared.valor : 0,
      lucro: i === 0 ? state.shared.lucro : 0
    }));

    await fillGoogleSheet(rows);

    const comissao = (toNumber(state.shared.lucro) || 0) * COMISSAO;
    ctx.reply(
      `✅ ${rows.length} linha(s) registrada(s)!\n\n` +
      `${rows.map((r) => '• ' + r.nome).join('\n')}\n\n` +
      `💰 Comissão (${Math.round(COMISSAO * 100)}%): R$ ${comissao.toFixed(2)}`
    );

    userState.delete(userId);
    initUserState(userId);
    ctx.reply('📄 Pronto para a próxima passagem! Envie um PDF (ou /manual).');
  } catch (error) {
    console.error(error);
    // Mantém tudo que foi digitado: dá para tentar de novo sem perder nada
    state.step = 'waiting_retry';
    ctx.reply(
      `❌ Não consegui salvar na planilha: ${error.message}\n\n` +
      `Seus dados foram guardados. Envie /retry para tentar de novo ou /restart para descartar.`
    );
  }
}

// ============================================================================
// INICIAR BOT
// ============================================================================

const PUBLIC_URL = process.env.RENDER_EXTERNAL_URL || process.env.PUBLIC_URL;
if (PUBLIC_URL) {
  // Nuvem (Render): webhook — o Telegram acorda o serviço quando chega mensagem
  bot
    .launch({
      webhook: {
        domain: PUBLIC_URL.replace(/^https?:\/\//, '').replace(/\/$/, ''),
        hookPath: '/telegram-webhook',
        port: Number(process.env.PORT) || 10000,
        secretToken: process.env.WEBHOOK_SECRET || undefined
      }
    })
    .then(() => console.log('🤖 Bot iniciado em modo webhook:', PUBLIC_URL))
    .catch((e) => { console.error('❌ Falha ao iniciar webhook:', e.message); process.exit(1); });
} else {
  // Local: polling
  bot.launch();
  console.log('🤖 Bot Telegram iniciado (polling)!');
}

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
