"""Oportunidades de lucro, análise por cliente, textos curtos e gráficos em imagem (PNG) para o Telegram.

A agência é intermediária. As vendas internacionais saem em consolidadoras (Ancoradouro e KG Travel): o cliente
paga no cartão, o valor vai para a companhia e o lucro cai direto na conta da agência. O risco é mínimo e a
comissão é baixa, então o jogo é volume, seguro e recorrência de clientes, e não "aumentar a margem" de cada bilhete.

Lucro bruto da venda = Base do imposto + Lucro não tributado + Comissão (a "Receita da agência" do painel).
Nacional x internacional vem do destino (aeroportos do itinerário), e não da companhia: a LATAM, a GOL e a Azul também voam para fora.
"""
import collections
import html
import json
import re
import statistics
from pathlib import Path

AEROPORTOS_BR = set(
    'GIG SDU GRU CGH VCP BSB CNF PLU POA FLN CWB VIX SSA REC FOR NAT MCZ AJU JPA SLZ THE BEL MAO CGB CGR GYN BPS IOS '
    'NVT JOI IGU FOZ LDB MGF UDI RAO SJK VDC CXJ PMW PVH RBR BVB MCP STM MAB IMP PNZ JDO CPV JJD LEC FEN RIO SAO JPR '
    'PET CKS ARU MOC IZA GVR UBA UNA CAW BGX CFB BAU AAX JCB CLV GEL ATM BJP SOD QSC ERM OAL FRC GPB JCM CIZ'.split())
CONSOLIDADORAS_RE = re.compile(r'ancorad\w*|kg\s*travel', re.I)
# Contas que NÃO são milhas: compra direto no site da cia, plataformas, hotéis e balcão. O restante (contas com nome de
# pessoa e programas como Smiles/Azul/Latam) é emissão em milhas.
SITE_RE = re.compile(r'site|pagante|expedi|taap|hotel|garden|turismo|seguro|coris|emirates|air france|qtar|qatar|^ita$|^tap$|'
                     r'avianca|thai|copa|easyjet|aerolineas|phillipine|cebu|american airlines|^aa (site|altera)|iberia|united|balc[aã]o|consultoria', re.I)
SEGURO_RE = re.compile(r'assist|coris|affinity|seguro|universal|gta\b', re.I)
PAR_RE = re.compile(r'\b[A-Z]{3}-[A-Z]{3}\b')
COMISSAO_SEGURO = 0.45     # comissão do seguro (informada pelo usuário)
META_ADESAO_SEGURO = 0.30  # meta: 3 em cada 10 bilhetes internacionais com seguro junto
PISO_EMISSAO = 100.0       # lucro mínimo desejado por emissão pequena (R$)
GANHO_COMISSAO = 0.005     # premissa: +0,5 ponto de comissão/incentivo por volume nas consolidadoras
CHANCE_VOLTAR = 0.30       # premissa: 30% dos recorrentes sumidos voltam a comprar 1 vez
CHANCE_2A_COMPRA = 0.10    # premissa: 10% dos clientes de compra única fazem uma 2ª compra
TIPOS = ['Nacional', 'Internacional · milhas', 'Internacional · site da cia', 'Internacional · consolidadora', 'Hotéis e outros', 'Seguro']
TIPOS_CURTO = ['Nacional', 'Intern. milhas', 'Intern. site cia', 'Intern. consolid.', 'Hotéis/outros', 'Seguro']


def lucro_bruto(t):
    return t['base'] + t['naotrib'] + t['com']


def eh_consolidadora(t):
    return bool(CONSOLIDADORAS_RE.search(t['conta']))


def canal(t):
    """'consolidadora' | 'site' (compra direto na cia/plataforma) | 'milhas' (conta de pessoa ou programa)."""
    if eh_consolidadora(t):
        return 'consolidadora'
    return 'site' if SITE_RE.search(t['conta'].strip()) else 'milhas'


def produto(t):
    """'seguro' | 'nacional' | 'internacional' | 'hotel' (hotéis e demais vendas sem trecho aéreo)."""
    if SEGURO_RE.search(t['cia']) or SEGURO_RE.search(t['conta']):
        return 'seguro'
    it = (t.get('ida', '') + ' ' + t.get('volta', '')).upper()
    if not PAR_RE.search(it):
        return 'hotel'
    codigos = re.findall(r'\b[A-Z]{3}\b', it)
    return 'nacional' if all(c in AEROPORTOS_BR for c in codigos) else 'internacional'


def tipo(t):
    p = produto(t)
    if p == 'nacional':
        return TIPOS[0]
    if p == 'internacional':
        return {'milhas': TIPOS[1], 'site': TIPOS[2], 'consolidadora': TIPOS[3]}[canal(t)]
    return TIPOS[4] if p == 'hotel' else TIPOS[5]


def nome_cia(k):
    """'UNITED/ AIR CANADA' -> 'United'; 'KLM' -> 'KLM'."""
    w = k.split('/')[0].split()[0] if k.strip() else 'Sem cia'
    return w.upper() if len(w) <= 3 else w.title()


def nome_curto(n):
    """Primeiro nome + segundo nome (ignora 'de', 'da'...)."""
    ignora = {'de', 'da', 'do', 'dos', 'das', 'e'}
    p = [w for w in n.split() if w]
    if not p:
        return '(sem nome)'
    resto = [w for w in p[1:] if w.lower() not in ignora][:1]
    return ' '.join(w.capitalize() for w in p[:1] + resto)


def abrev(nome):
    """'Manuela Santos' -> 'Manuela S.' (cabe nas tabelas do celular)."""
    p = nome.split()
    return f'{p[0]} {p[1][0]}.' if len(p) > 1 and p[0] != 'Empresa' else nome


_CACHE_CNPJ = {}
_SUFIXOS = re.compile(r'\s+(LTDA|ME|EPP|EIRELI|S/?A|SS|MEI)\.?$', re.I)


def _carrega_cache():
    if not _CACHE_CNPJ:
        try:
            _CACHE_CNPJ.update(json.loads((Path(__file__).parent / 'cnpj_nomes.json').read_text()))
        except (OSError, ValueError):
            pass
    return _CACHE_CNPJ


def nome_empresa(cnpj):
    """Nome da empresa (nome fantasia, ou razão social sem 'LTDA'). Usa o cache cnpj_nomes.json e, se o CNPJ for novo,
    consulta a BrasilAPI (cadastro público da Receita). Sem resposta, cai em 'Empresa <início do CNPJ>'."""
    cache = _carrega_cache()
    if cnpj in cache:
        return cache[cnpj]
    nome = ''
    try:
        import requests
        resp = requests.get(f'https://brasilapi.com.br/api/cnpj/v1/{cnpj}', timeout=10)
        if resp.status_code == 200:
            j = resp.json()
            nome = (j.get('nome_fantasia') or '').strip() or _SUFIXOS.sub('', (j.get('razao_social') or '').strip())
            nome = ' '.join(w.capitalize() if len(w) > 3 else w for w in nome.split()).strip()
    except Exception:
        nome = ''
    cache[cnpj] = nome or f'Empresa {cnpj[:6]}'
    return cache[cnpj]


def chave_cliente(t):
    """CPF (ou nome, se não houver documento). CNPJ agrupa pela raiz (8 dígitos): matriz e filial são a mesma empresa."""
    doc = re.sub(r'\D', '', t['cpf'])
    if len(doc) == 14:
        return 'CNPJ' + doc[:8]
    return doc if len(doc) >= 11 else (t['nome'].upper().strip() or '?')


def curto(c):
    """Rótulo curto de cliente para tabelas e gráficos."""
    return ' '.join(c['nome'].split()[:2]) if c['empresa'] else abrev(c['nome'])


def mil(v):
    """R$ 1,89 mi / R$ 252 mil / R$ 9,5 mil / R$ 950."""
    a = abs(v)
    if a >= 1e6:
        s = f'{a / 1e6:.2f} mi'
    elif a >= 1e4:
        s = f'{a / 1e3:.0f} mil'
    elif a >= 1e3:
        s = f'{a / 1e3:.1f} mil'
    else:
        s = f'{a:.0f}'
    return ('−' if v < 0 else '') + 'R$ ' + s.replace('.', ',')


def analisar(vend, M, sem_pag, S, brl, pct):
    n_meses = len(M)
    ref = M[-1]['m']
    for t in vend:
        t['_tipo'] = tipo(t)
    seg = [t for t in vend if produto(t) == 'seguro']
    inter = [t for t in vend if produto(t) == 'internacional']
    pas = [t for t in vend if produto(t) in ('nacional', 'internacional')]
    soma = lambda g, k=None: sum((lucro_bruto(t) if k is None else t[k]) for t in g)
    V, L = soma(vend, 'valor'), soma(vend)

    mes = []
    for m in M:
        g = [t for t in vend if t['mes'] == m['m']]
        mes.append(dict(label=m['label'], vendas=soma(g, 'valor'), lucro=soma(g),
                        lucro_seg=soma([t for t in g if produto(t) == 'seguro']), n=len(g)))

    tipos = []
    for nome, curto in zip(TIPOS, TIPOS_CURTO):
        g = [t for t in vend if t['_tipo'] == nome]
        if g:
            v_, l_ = soma(g, 'valor'), soma(g)
            tipos.append(dict(nome=nome, curto=curto, n=len(g), valor=v_, lucro=l_, por_venda=l_ / len(g), margem=l_ / v_ if v_ else 0))
    por_tipo = {x['nome']: x for x in tipos}

    # ---- por cliente ----
    grupos = collections.defaultdict(list)
    for t in vend:
        grupos[chave_cliente(t)].append(t)
    clientes = []
    for k, g in grupos.items():
        v_, l_ = soma(g, 'valor'), soma(g)
        cnpjs = [re.sub(r'\D', '', t['cpf']) for t in g if len(re.sub(r'\D', '', t['cpf'])) == 14]
        empresa = bool(cnpjs)
        cnpj = collections.Counter(cnpjs).most_common(1)[0][0] if empresa else ''
        clientes.append(dict(
            k=k, empresa=empresa, cnpj=(f'{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}' if empresa else ''),
            pax=len({t['nome'].strip().lower() for t in g}),
            nome=nome_empresa(cnpj) if empresa else nome_curto(max(g, key=lambda t: len(t['nome']))['nome']),
            n=len(g), valor=v_, lucro=l_,
            margem=l_ / v_ if v_ else 0, por_compra=l_ / len(g), ultima=max(t['mes'] for t in g),
            n_inter=sum(1 for t in g if produto(t) == 'internacional'), tem_seguro=any(produto(t) == 'seguro' for t in g)))
    clientes.sort(key=lambda c: -c['lucro'])
    lucro_cli = sum(c['lucro'] for c in clientes)
    seg_cli = {}
    for nome, cond in (('recorrentes', lambda c: c['n'] >= 3), ('ocasionais', lambda c: c['n'] == 2), ('unicos', lambda c: c['n'] == 1)):
        g = [c for c in clientes if cond(c)]
        seg_cli[nome] = dict(n=len(g), lucro=sum(c['lucro'] for c in g), share=sum(c['lucro'] for c in g) / lucro_cli if lucro_cli else 0)
    recorrentes = [c for c in clientes if c['n'] >= 3]
    sumidos = [c for c in clientes if c['n'] >= 2 and c['ultima'] <= ref - 3]
    unicos = [c for c in clientes if c['n'] == 1]
    sem_seguro = sorted([c for c in clientes if c['n_inter'] >= 2 and not c['tem_seguro']], key=lambda c: -c['n_inter'])
    melhores_margens = sorted([c for c in recorrentes if c['lucro'] >= 1000], key=lambda c: -c['margem'])[:5]

    # ---- oportunidades ----
    ops = []
    lucros_seg = [lucro_bruto(t) for t in seg]
    seg_med = sum(lucros_seg) / len(seg) if seg else 0
    seg_mediana = statistics.median(lucros_seg) if seg else 0
    adesao = len(seg) / len(inter) if inter else 0
    baixas_seg = [t for t in seg if t['valor'] > 0 and lucro_bruto(t) / t['valor'] < 0.35]
    if seg and inter:
        extra = max(0, META_ADESAO_SEGURO - adesao) * len(inter)
        aviso = ''
        if baixas_seg:
            nomes_b = ' e '.join(f'{t["cia"].strip().title()} ({pct(lucro_bruto(t) / t["valor"], 0)})' for t in baixas_seg[:3])
            aviso = f' Atenção: {nomes_b} {'deixou' if len(baixas_seg) == 1 else 'deixaram'} menos que os {pct(COMISSAO_SEGURO, 0)} das outras apólices. Prefira as seguradoras que pagam mais.'
        ops.append(dict(
            chave='seguro', curto='Seguro em mais bilhetes internacionais', ganho=extra * seg_mediana, esforco='Baixo',
            por_que=f'Você vendeu {len(seg)} seguros para {len(inter)} bilhetes internacionais ({pct(adesao, 0)}). Como a comissão é de {pct(COMISSAO_SEGURO, 0)}, '
                    f'uma apólice típica deixa {brl(seg_mediana)} (média de {brl(seg_med)}), sem risco. '
                    f'{len(sem_seguro)} clientes com 2 ou mais bilhetes internacionais nunca compraram seguro com você.' + aviso,
            passo='Colocar o seguro na cotação de todo bilhete internacional (Coris, Assist Card, Affinity...), com 2 opções: básico e completo. '
                  'Começar pelos clientes recorrentes da lista abaixo.',
            premissa=f'Estimativa conservadora: subir de {pct(adesao, 0)} para {pct(META_ADESAO_SEGURO, 0)} dos bilhetes internacionais, com o lucro mediano por apólice da sua planilha '
                     f'(com a média, seria {mil(extra * seg_med)}).'))
    cons = [t for t in inter if eh_consolidadora(t)]
    v_cons = soma(cons, 'valor')
    if cons:
        ops.append(dict(
            chave='comissao', curto='Melhor comissão nas consolidadoras', ganho=v_cons * GANHO_COMISSAO, esforco='Médio',
            por_que=f'Você movimentou {mil(v_cons)} em {len(cons)} bilhetes internacionais nas consolidadoras (Ancoradouro/KG Travel) e o lucro foi de {pct(soma(cons) / v_cons)} desse volume. '
                    'Como o ganho é comissão sobre o volume, o volume é o seu argumento de negociação.',
            passo='Levar o volume por cia e por mês para a consolidadora e pedir incentivo por meta (comissão maior acima de um volume mensal). '
                  'Cotar a mesma cia nas duas consolidadoras e concentrar onde pagar mais.',
            premissa=f'Estimativa: +{pct(GANHO_COMISSAO).replace("%", " ponto percentual")} de comissão sobre o volume das consolidadoras. Depende do que elas aceitarem.'))
    i_milhas = [t for t in inter if canal(t) == 'milhas']
    i_outros = [t for t in inter if canal(t) != 'milhas']
    if i_milhas and i_outros:
        l_m, l_o = soma(i_milhas) / len(i_milhas), soma(i_outros) / len(i_outros)
        if l_m > l_o:
            n_troca = 0.10 * len(i_outros)
            ops.append(dict(
                chave='milhas', curto='Emitir mais internacional em milhas', ganho=n_troca * (l_m - l_o), esforco='Médio',
                por_que=f'O bilhete internacional emitido em milhas deixa {brl(l_m)} por venda, contra {brl(l_o)} no site da cia e nas consolidadoras '
                        f'({len(i_milhas)} vendas em milhas, {len(i_outros)} nos outros canais).',
                passo='Quando houver saldo de milhas para a rota, cotar primeiro em milhas e só depois no site ou na consolidadora. '
                      'Priorizar milhas nas rotas e nos clientes recorrentes que voltam a comprar a mesma viagem.',
                premissa=f'Estimativa: 10% das vendas internacionais dos outros canais ({n_troca:.0f} vendas) passam para milhas. Depende do seu saldo de milhas.'))
    if sumidos:
        ops.append(dict(
            chave='reativar', curto='Reativar recorrentes que sumiram', ganho=CHANCE_VOLTAR * sum(c['por_compra'] for c in sumidos), esforco='Baixo',
            por_que=f'{len(sumidos)} clientes que compraram 2 vezes ou mais não compram há 3 meses ou mais (lucro médio de {brl(sum(c["por_compra"] for c in sumidos) / len(sumidos))} por compra).',
            passo='Mensagem pessoal no WhatsApp: perguntar da próxima viagem e mandar uma cotação já pronta na rota que ele costuma fazer.',
            premissa=f'Estimativa: {pct(CHANCE_VOLTAR, 0)} deles compram 1 vez de novo.'))
    if unicos:
        ops.append(dict(
            chave='segunda', curto='Fazer o cliente de 1 compra voltar', ganho=CHANCE_2A_COMPRA * sum(c['por_compra'] for c in unicos), esforco='Médio',
            por_que=f'{len(unicos)} clientes compraram só 1 vez ({pct(seg_cli["unicos"]["share"], 0)} do lucro). Fazer um cliente voltar custa muito menos que conquistar um novo.',
            passo='Falar com o cliente 7 dias depois da viagem (pedir indicação e oferecer a próxima) e de novo 45 dias antes da mesma época no ano seguinte.',
            premissa=f'Estimativa: {pct(CHANCE_2A_COMPRA, 0)} deles fazem uma 2ª compra.'))
    peq = [t for t in pas if t['valor'] < 5000 and lucro_bruto(t) < PISO_EMISSAO]
    falta = sum(PISO_EMISSAO - lucro_bruto(t) for t in peq)
    ops.append(dict(
        chave='piso', curto='Piso de lucro por emissão', ganho=falta * 0.5, esforco='Baixo',
        por_que=f'{len(peq)} emissões deixaram menos de {brl(PISO_EMISSAO).replace(",00", "")} de lucro. Emitir dá o mesmo trabalho com R$ 30 ou com R$ 300.',
        passo='Cobrar uma taxa de serviço nas emissões pequenas até o lucro chegar ao piso. Comece pelos clientes novos.',
        premissa=f'Estimativa: só metade dos casos aceita ({mil(falta)} se todos aceitassem).'))
    ops.sort(key=lambda o: -o['ganho'])

    return dict(
        V=V, L=L, n=len(vend), n_meses=n_meses, mes=mes, tipos=tipos, por_tipo=por_tipo, ops=ops, total=sum(o['ganho'] for o in ops),
        n_inter=len(inter), l_inter=soma(inter), v_inter=soma(inter, 'valor'),
        seg=dict(n=len(seg), valor=soma(seg, 'valor'), lucro=soma(seg), margem=soma(seg) / soma(seg, 'valor') if seg else 0,
                 med=seg_med, mediana=seg_mediana, adesao=adesao),
        clientes=clientes, lucro_cli=lucro_cli, seg_cli=seg_cli, recorrentes=recorrentes, sumidos=sumidos, unicos=unicos,
        sem_seguro=sem_seguro, melhores_margens=melhores_margens, ref=ref, sem_pag=(len(sem_pag), soma(sem_pag, 'valor')),
    )


# ---------- textos (Telegram, HTML) ----------
def sequencia(O, parcial, rotulo_fim, res, top_conta, R, brl, pct, meses_abrev, imgs):
    """Lista ordenada de ('texto', str) e ('imagem', (Path, legenda)) para enviar ao Telegram."""
    esc = html.escape
    c1 = O['clientes'][0]
    share1 = c1['lucro'] / O['lucro_cli']

    linhas_tipo = []
    for x in O['tipos']:
        linhas_tipo.append(f'• {esc(x["nome"])}: <b>{brl(x["por_venda"])}</b> por venda ({x["n"]} vendas, {pct(x["margem"], 0)} do valor)')
    m1 = (f'<b>Agência do Futuro · até {rotulo_fim}</b>\n'
          f'Passaram pela agência <b>{mil(O["V"])}</b> em {O["n"]} vendas (quase tudo vai direto para as cias aéreas). '
          f'O lucro bruto foi de <b>{mil(O["L"])}</b>, uns <b>{mil(O["L"] / O["n_meses"])} por mês</b>.\n'
          f'Depois de custos e comissões, o lucro do ano é <b>{brl(res)}</b> (média de {brl(res / O["n_meses"])}/mês).\n\n'
          '<b>Quanto cada tipo de venda deixa, em média</b>\n' + '\n'.join(linhas_tipo) + '\n\n'
          'No internacional você ganha comissão sobre o volume, com risco mínimo. O que muda o resultado é vender mais bilhetes, '
          'vender o seguro junto e fazer o cliente voltar.\n'
          f'Cada 10% a mais de bilhetes internacionais = <b>+{mil(O["l_inter"] * 0.1 / O["n_meses"])} por mês</b>.')

    linhas = [f'<b>Onde dá para ganhar mais</b>\nPotencial estimado: <b>+{mil(O["total"])}</b> no período (≈ {mil(O["total"] / O["n_meses"])}/mês), '
              'somando as ideias abaixo. São estimativas, não promessas.\n']
    for i, o in enumerate(O['ops'], 1):
        linhas.append(f'<b>{i}. {esc(o["curto"])}</b> · +{mil(o["ganho"])} · esforço {o["esforco"].lower()}\n'
                      f'{esc(o["por_que"])}\n<i>Como:</i> {esc(o["passo"])}\n<i>{esc(o["premissa"])}</i>\n')
    m2 = '\n'.join(linhas)

    tab = ['Tipo               Vendas Lucro/venda Marg.', '-' * 41]
    for x in O['tipos']:
        tab.append(f'{x["curto"]:<17} {x["n"]:>6} {mil(x["por_venda"]).replace("R$ ", ""):>10} {pct(x["margem"]):>6}')
    m3 = ('<b>Por tipo de venda</b>\n<pre>' + '\n'.join(tab) + '</pre>\n'
          '<i>Nacional ou internacional pelo destino do voo. Milhas = contas com nome de pessoa e programas (Smiles, Azul, Latam). '
          'Site da cia = compra direto na cia ou plataforma. Consolidadora = Ancoradouro e KG Travel.</i>')

    sc = O['seg_cli']
    tabc = ['Cliente       Comp. Lucro  Marg. Últ.', '-' * 36]
    for c in O['clientes'][:8]:
        tabc.append(f'{curto(c)[:13]:<13} {c["n"]:>4} {mil(c["lucro"]).replace("R$ ", ""):>6} {pct(c["margem"], 0):>5} {meses_abrev[c["ultima"] - 1]:>4}')
    m5 = (f'<b>Seus clientes ({len(O["clientes"])} no período)</b>\n'
          f'• <b>{sc["recorrentes"]["n"]} recorrentes</b> (3+ compras) geram <b>{pct(sc["recorrentes"]["share"], 0)}</b> do lucro bruto.\n'
          f'• {sc["ocasionais"]["n"]} ocasionais (2 compras): {pct(sc["ocasionais"]["share"], 0)}.\n'
          f'• {sc["unicos"]["n"]} de compra única: {pct(sc["unicos"]["share"], 0)}.\n'
          + (f'• O maior cliente é a empresa <b>{esc(c1["nome"])}</b> (CNPJ {c1["cnpj"]}, {c1["pax"]} passageiros diferentes): sozinha é <b>{pct(share1, 0)}</b> do lucro, com {c1["n"]} compras.\n\n'
             if c1['empresa'] else f'• O maior cliente ({esc(c1["nome"])}) sozinho é <b>{pct(share1, 0)}</b> do lucro, com {c1["n"]} compras.\n\n')
          + '<b>Maiores clientes por lucro</b>\n<pre>' + '\n'.join(tabc) + '</pre>')
    if O['melhores_margens']:
        m5 += '\n<b>Melhores margens entre os recorrentes</b>\n' + '\n'.join(
            f'• {esc(c["nome"])}: {pct(c["margem"])} em {c["n"]} compras ({mil(c["lucro"])})' for c in O['melhores_margens'])

    acoes = ['<b>O que fazer com os clientes recorrentes</b>']
    if O['sem_seguro']:
        nomes = ', '.join(esc(c['nome']) for c in O['sem_seguro'][:5])
        acoes.append(f'1. <b>Vender seguro para quem já viaja com você:</b> {nomes} têm 2+ bilhetes internacionais e nenhum seguro comprado com você.')
    if c1['n'] >= 12:
        quem = f'a empresa {esc(c1["nome"])}, {c1["pax"]} passageiros' if c1['empresa'] else esc(c1['nome'])
        acoes.append(f'2. <b>Formalizar o maior cliente</b> ({quem}, {c1["n"]} compras, {pct(share1, 0)} do lucro): '
                     'contrato com taxa de serviço mensal ou prioridade de atendimento. Hoje um único cliente sustenta boa parte do resultado.')
    alto_vol = [c for c in O['recorrentes'] if c['margem'] < 0.05 and c['valor'] >= 50000]
    if alto_vol:
        acoes.append(f'3. <b>Alto volume e comissão baixa</b> ({", ".join(esc(c["nome"]) for c in alto_vol[:3])}): '
                     'some hotel, seguro e transfer na mesma venda para subir o lucro por cliente.')
    if O['sumidos']:
        n_ = ', '.join(esc(c['nome']) for c in sorted(O['sumidos'], key=lambda c: -c['lucro'])[:5])
        acoes.append(f'4. <b>Reativar quem sumiu</b> (3+ meses sem comprar): {n_}. Mande uma cotação pronta na rota que costumam fazer.')
    acoes.append('5. <b>Chamar 45 dias antes da próxima viagem:</b> anote em que mês cada recorrente costuma viajar. É quando a tarifa ainda está boa e ele ainda não cotou com outra agência.')
    acoes.append('6. <b>Pedir indicação</b> aos clientes de melhor margem, logo depois da viagem.')
    m6 = '\n\n'.join(acoes)

    aten = []
    if O['sem_pag'][0]:
        aten.append(f'• {O["sem_pag"][0]} vendas ({mil(O["sem_pag"][1])}) sem forma de pagamento anotada: confirme se o dinheiro entrou.')
    if top_conta:
        aten.append(f'• A conta "{esc(top_conta[0].title())}" emite {pct(top_conta[1] / O["V"], 0)} do volume. Se ela travar, o faturamento trava junto.')
    if R:
        aten.append(f'• Suas retiradas: {brl(R["ret"])} no ano, contra um direito de {brl(R["dir"])} (saldo acumulado {brl(R["fim"])}).')
    m4 = '<b>Atenção</b>\n' + '\n'.join(aten) if aten else ''

    seq = [('texto', m1), ('imagem', imgs['lucro']), ('imagem', imgs['tipos']), ('texto', m3), ('texto', m2), ('imagem', imgs['oportunidades']),
           ('texto', m5), ('imagem', imgs['clientes']), ('texto', m6)]
    if m4:
        seq.append(('texto', m4))
    return seq


# ---------- gráficos (PNG) ----------
INK, MUTED, GRID, ACCENT, ACCENT2, NEUTRAL = '#1f2933', '#6b7785', '#e3e7ec', '#2f6fdb', '#e08a1e', '#a9b3bf'


def _base(titulo, sub):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'text.color': INK, 'axes.edgecolor': GRID, 'text.parse_math': False})
    fig, ax = plt.subplots(figsize=(7.2, 4.4), dpi=150)
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')
    for s in ('top', 'right', 'left'):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=MUTED, length=0)
    fig.text(0.04, 0.95, titulo, fontsize=13, fontweight='bold', va='top', color=INK)
    fig.text(0.04, 0.885, sub, fontsize=9, va='top', color=MUTED)
    return fig, ax, plt


def _pct(v):
    return f'{v * 100:.1f}'.replace('.', ',') + '%'


def _salva(fig, plt, out, nome):
    p = out / nome
    fig.savefig(p)
    plt.close(fig)
    return p


def graficos(O, out, sufixo):
    """Retorna dict nome -> (caminho, legenda)."""
    imgs = {}

    # 1) lucro bruto por mês (passagens + seguros), com o volume embaixo de cada mês
    fig, ax, plt = _base('Quanto a agência ganhou por mês', 'Lucro bruto (antes de comissões e custos). Embaixo de cada mês: quanto passou pela agência')
    xs = list(range(len(O['mes'])))
    pas = [m['lucro'] - m['lucro_seg'] for m in O['mes']]
    sg = [m['lucro_seg'] for m in O['mes']]
    topo = max(m['lucro'] for m in O['mes'])
    ax.bar(xs, pas, color=ACCENT, width=0.62, label='Passagens e hotéis')
    ax.bar(xs, sg, bottom=pas, color=ACCENT2, width=0.62, label='Seguros')
    for x, m in zip(xs, O['mes']):
        ax.text(x, m['lucro'] + topo * 0.02, mil(m['lucro']).replace('R$ ', ''), ha='center', fontsize=8.5, color=INK)
    ax.set_xticks(xs)
    ax.set_xticklabels([f'{m["label"][:3]}\n{mil(m["vendas"]).replace("R$ ", "")}' for m in O['mes']], fontsize=8)
    ax.set_ylim(0, topo * 1.2)
    ax.yaxis.set_visible(False)
    ax.legend(loc='upper left', frameon=False, fontsize=8.5, ncol=2)
    fig.subplots_adjust(top=0.80, bottom=0.14, left=0.04, right=0.98)
    imgs['lucro'] = (_salva(fig, plt, out, f'lucro-mensal-{sufixo}.png'),
                     'Lucro bruto por mês (azul = passagens e hotéis, laranja = seguros). Embaixo do mês: quanto passou pela agência.')

    # 2) quanto cada tipo de venda deixa
    tp = O['tipos'][::-1]
    fig, ax, plt = _base('Quanto cada tipo de venda deixa', 'Barra = lucro médio por venda. Texto = vendas, volume que passou e % do valor')
    ys = list(range(len(tp)))
    ax.barh(ys, [x['por_venda'] for x in tp], color=[ACCENT2 if x['nome'] == 'Seguro' else ACCENT for x in tp], height=0.62)
    ax.set_yticks(ys)
    ax.set_yticklabels([x['curto'] for x in tp], fontsize=9, color=INK)
    mx = max(x['por_venda'] for x in tp)
    for y, x in zip(ys, tp):
        ax.text(x['por_venda'] + mx * 0.015, y, f'R$ {x["por_venda"]:.0f} · {x["n"]} vendas · {mil(x["valor"])} · {_pct(x["margem"])}', va='center', fontsize=8.5, color=INK)
    ax.set_xlim(0, mx * 2.25)
    ax.xaxis.set_visible(False)
    fig.subplots_adjust(top=0.80, bottom=0.05, left=0.19, right=0.98)
    imgs['tipos'] = (_salva(fig, plt, out, f'tipos-{sufixo}.png'),
                     'Lucro médio por venda em cada tipo. Nacional e internacional são separados pelo destino do voo.')

    # 3) maiores clientes por lucro
    cl = O['clientes'][:8][::-1]
    fig, ax, plt = _base('Seus maiores clientes por lucro', 'Barra = lucro bruto no período. Texto = compras e margem. Azul = recorrente (3+ compras)')
    ys = list(range(len(cl)))
    ax.barh(ys, [c['lucro'] for c in cl], color=[ACCENT if c['n'] >= 3 else NEUTRAL for c in cl], height=0.62)
    ax.set_yticks(ys)
    ax.set_yticklabels([curto(c) for c in cl], fontsize=9, color=INK)
    mx = max(c['lucro'] for c in cl)
    for y, c in zip(ys, cl):
        ax.text(c['lucro'] + mx * 0.015, y, f'{mil(c["lucro"])} · {c["n"]} compras · {_pct(c["margem"])}', va='center', fontsize=8.5, color=INK)
    ax.set_xlim(0, mx * 1.7)
    ax.xaxis.set_visible(False)
    fig.subplots_adjust(top=0.80, bottom=0.05, left=0.25, right=0.98)
    imgs['clientes'] = (_salva(fig, plt, out, f'clientes-{sufixo}.png'), 'Maiores clientes por lucro bruto.')

    # 4) oportunidades
    ops = O['ops'][::-1]
    fig, ax, plt = _base('Onde dá para ganhar mais', f'Ganho estimado no período (estimativa). Total: +{mil(O["total"])}')
    ys = list(range(len(ops)))
    ax.barh(ys, [o['ganho'] for o in ops], color=ACCENT, height=0.6)
    ax.set_yticks(ys)
    ax.set_yticklabels([o['curto'] for o in ops], fontsize=8.5, color=INK)
    mx = max(o['ganho'] for o in ops)
    for y, o in zip(ys, ops):
        ax.text(o['ganho'] + mx * 0.015, y, f'+{mil(o["ganho"])}', va='center', fontsize=9, color=INK)
    ax.set_xlim(0, mx * 1.3)
    ax.xaxis.set_visible(False)
    fig.subplots_adjust(top=0.80, bottom=0.05, left=0.45, right=0.97)
    imgs['oportunidades'] = (_salva(fig, plt, out, f'oportunidades-{sufixo}.png'), 'Ganho estimado por oportunidade (estimativas).')
    return imgs
