"""Oportunidades de lucro, análise por cliente, textos curtos e gráficos em imagem (PNG) para o Telegram.

A agência é intermediária. As vendas internacionais saem em consolidadoras (Ancoradouro e KG Travel): o cliente
paga no cartão, o valor vai para a companhia e o lucro cai direto na conta da agência. O risco é mínimo e a
comissão é baixa, então o jogo é volume, seguro e recorrência de clientes, e não "aumentar a margem" de cada bilhete.

Lucro bruto da venda = Base do imposto + Lucro não tributado + Comissão (a "Receita da agência" do painel).
Nacional x internacional vem do destino (aeroportos do itinerário), e não da companhia: a LATAM, a GOL e a Azul também voam para fora.
"""
import collections
import datetime as dt
import html
import json
import re
import statistics
from pathlib import Path

AEROPORTOS_BR = set(
    'GIG SDU GRU CGH VCP BSB CNF PLU POA FLN CWB VIX SSA REC FOR NAT MCZ AJU JPA SLZ THE BEL MAO CGB CGR GYN BPS IOS '
    'NVT JOI IGU FOZ LDB MGF UDI RAO SJK VDC CXJ PMW PVH RBR BVB MCP STM MAB IMP PNZ JDO CPV JJD LEC FEN RIO SAO JPR '
    'PET CKS ARU MOC IZA GVR UBA UNA CAW BGX CFB BAU AAX JCB CLV GEL ATM BJP SOD QSC ERM OAL FRC GPB JCM CIZ SJP OPS'.split())
CONSOLIDADORAS_RE = re.compile(r'ancorad\w*|kg\s*travel', re.I)
# Contas que NÃO são milhas: compra direto no site da cia, plataformas, hotéis e balcão. O restante (contas com nome de
# pessoa e programas como Smiles/Azul/Latam) é emissão em milhas.
SITE_RE = re.compile(r'site|pagante|expedi|taap|hotel|garden|turismo|seguro|coris|emirates|air france|qtar|qatar|^ita$|^tap$|'
                     r'avianca|thai|copa|easyjet|aerolineas|phillipine|cebu|american airlines|^aa (site|altera)|iberia|united|balc[aã]o|consultoria', re.I)
HOTEL_RE = re.compile(r'expedi|taap|hotel|garden', re.I)
HOTEL_CIA_RE = re.compile(r'hotel|lodge|resort|boutique|villas?|apartment|suites?', re.I)
SERVICO_RE = re.compile(r'localiza|hertz|movida|unidas|\bavis\b|altera', re.I)   # aluguel de carro e remarcação
SEGURO_RE = re.compile(r'assist|assit|coris|affinity|seguro|universal|gta\b', re.I)   # 'assit' = grafia errada de Assist Card na planilha
PAR_RE = re.compile(r'\b[A-Z]{3}-[A-Z]{3}\b')
COMISSAO_SEGURO = 0.45     # comissão do seguro (informada pelo usuário)
META_ADESAO_SEGURO = 0.30  # meta: 3 em cada 10 bilhetes internacionais com seguro junto
PISO_EMISSAO = 100.0       # lucro mínimo desejado por emissão pequena (R$)
GANHO_COMISSAO = 0.005     # premissa: +0,5 ponto de comissão/incentivo por volume nas consolidadoras
CHANCE_VOLTAR = 0.30       # premissa: 30% dos recorrentes sumidos voltam a comprar 1 vez
CHANCE_2A_COMPRA = 0.10    # premissa: 10% dos clientes de compra única fazem uma 2ª compra
TIPOS = ['Nacional', 'Internacional · milhas', 'Internacional · site da cia', 'Internacional · consolidadora', 'Hotel', 'Outros serviços', 'Seguro']
TIPOS_CURTO = ['Nacional', 'Intern. milhas', 'Intern. site cia', 'Intern. consolid.', 'Hotel', 'Outros serviços', 'Seguro']
CATEGORIAS = ['Passagem', 'Hotel', 'Seguro', 'Outros serviços']


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
    """'seguro' | 'nacional' | 'internacional' | 'hotel' | 'servico' (aluguel de carro, remarcação e demais sem trecho aéreo)."""
    if SEGURO_RE.search(t['cia']) or SEGURO_RE.search(t['conta']):
        return 'seguro'
    it = (t.get('ida', '') + ' ' + t.get('volta', '')).upper()
    if not PAR_RE.search(it):
        if SERVICO_RE.search(t['cia']) or SERVICO_RE.search(t['conta']):
            return 'servico'
        return 'hotel' if (HOTEL_RE.search(t['conta']) or HOTEL_CIA_RE.search(t['cia'])) else 'servico'
    codigos = re.findall(r'\b[A-Z]{3}\b', it)
    return 'nacional' if all(c in AEROPORTOS_BR for c in codigos) else 'internacional'


def tipo(t):
    p = produto(t)
    if p == 'nacional':
        return TIPOS[0]
    if p == 'internacional':
        return {'milhas': TIPOS[1], 'site': TIPOS[2], 'consolidadora': TIPOS[3]}[canal(t)]
    return {'hotel': TIPOS[4], 'servico': TIPOS[5], 'seguro': TIPOS[6]}[p]


def categoria(t):
    p = produto(t)
    return {'nacional': 'Passagem', 'internacional': 'Passagem', 'hotel': 'Hotel', 'seguro': 'Seguro', 'servico': 'Outros serviços'}[p]


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
    consulta a BrasilAPI (cadastro público da Receita). Sem resposta, mostra o próprio CNPJ (nunca inventa nome)."""
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
    if not nome:  # sem resposta: mostra o próprio CNPJ, sem inventar nome
        return f'CNPJ {cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}'
    cache[cnpj] = nome
    return nome


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


CIDADES = {'POA': 'Porto Alegre', 'GIG': 'Rio (Galeão)', 'SDU': 'Rio (Santos Dumont)', 'GRU': 'São Paulo (Guarulhos)',
           'CGH': 'São Paulo (Congonhas)', 'GYN': 'Goiânia', 'SCL': 'Santiago', 'FEN': 'Fernando de Noronha'}


def rota_par(rota):
    """'POA-GYN' e 'GYN-POA' são a mesma rota (ida e volta somadas). Sem trecho aéreo, devolve None."""
    cods = re.findall(r'\b[A-Z]{3}\b', rota.upper())
    if len(cods) < 2:
        return None
    a, b = cods[0], cods[-1]
    return ' – '.join(sorted((a, b)))


def insights_retiradas(itens, R):
    """Onde as retiradas em passagens se concentram: por rota, por pessoa, por cia e por mês (data do lançamento)."""
    if not itens:
        return None
    total = sum(x['valor'] for x in itens)
    rotas = collections.defaultdict(lambda: dict(n=0, valor=0.0))
    sem_rota = []
    for x in itens:
        p = rota_par(x['rota'])
        if p is None:
            sem_rota.append(x)
            continue
        rotas[p]['n'] += 1
        rotas[p]['valor'] += x['valor']
    rotas = sorted(([k, v['n'], v['valor']] for k, v in rotas.items()), key=lambda z: -z[2])
    pessoas = collections.defaultdict(lambda: [0, 0.0])
    for x in itens:
        k = x['nome'].split()[0] if x['nome'].strip() else '(sem nome)'
        pessoas[k][0] += 1
        pessoas[k][1] += x['valor']
    pessoas = sorted(([k, v[0], v[1]] for k, v in pessoas.items()), key=lambda z: -z[2])
    cias = collections.defaultdict(float)
    for x in itens:
        cias[nome_cia(x['cia']) if x['cia'].strip() not in ('', '-') else '(sem cia)'] += x['valor']
    meses = collections.defaultdict(float)
    for x in itens:
        meses[x['data'].month] += x['valor']
    # mesma rota, mesma data, duas pessoas: retirada em dobro
    grupos = collections.defaultdict(list)
    for x in itens:
        p = rota_par(x['rota'])
        if p:
            grupos[(x['data'], x['rota'].upper())].append(x)
    dobradas = [g for g in grupos.values() if len({y['nome'] for y in g}) > 1]
    return dict(itens=itens, total=total, n=len(itens), medio=total / len(itens), rotas=rotas, sem_rota=sem_rota, pessoas=pessoas,
                cias=sorted(cias.items(), key=lambda z: -z[1]), meses=dict(meses), dobradas=dobradas)


def analisar(vend, M, sem_pag, S, brl, pct, hoje):
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

    # ---- retorno por categoria (o que oferecer ao cliente) ----
    categorias = []
    for nome in CATEGORIAS:
        g = [t for t in vend if categoria(t) == nome]
        if g:
            v_, l_ = soma(g, 'valor'), soma(g)
            categorias.append(dict(nome=nome, n=len(g), valor=v_, lucro=l_, por_venda=l_ / len(g), margem=l_ / v_ if v_ else 0,
                                   share=l_ / L if L else 0, clientes=len({chave_cliente(t) for t in g})))

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
            nome=nome_empresa(cnpj) if empresa else nome_curto(collections.Counter(t['nome'].strip() for t in g).most_common(1)[0][0]),
            n=len(g), valor=v_, lucro=l_,
            margem=l_ / v_ if v_ else 0, por_compra=l_ / len(g), ultima=max(t['mes'] for t in g),
            n_inter=sum(1 for t in g if produto(t) == 'internacional'), tem_seguro=any(produto(t) == 'seguro' for t in g),
            tem_hotel=any(produto(t) == 'hotel' for t in g)))
    clientes.sort(key=lambda c: -c['lucro'])
    lucro_cli = sum(c['lucro'] for c in clientes)
    acum = 0.0
    for c in clientes:  # faixa A = os que somam até 50% do lucro; B = até 80%; C = o resto
        c['faixa'] = 'A' if acum < 0.5 * lucro_cli else ('B' if acum < 0.8 * lucro_cli else 'C')
        acum += c['lucro']
        c['falta'] = [nome for nome, cond in (('seguro', not c['tem_seguro']), ('hotel', not c['tem_hotel'])) if c['n_inter'] > 0 and cond]
    faixas = {f: dict(n=sum(1 for c in clientes if c['faixa'] == f), lucro=sum(c['lucro'] for c in clientes if c['faixa'] == f)) for f in 'ABC'}
    em_risco = sorted([c for c in clientes if c['faixa'] in 'AB' and c['ultima'] <= ref - 3], key=lambda c: -c['lucro'])
    inter_cli = [c for c in clientes if c['n_inter'] > 0]
    penetracao = dict(n=len(inter_cli), hotel=sum(1 for c in inter_cli if c['tem_hotel']), seguro=sum(1 for c in inter_cli if c['tem_seguro']))

    # ---- viagens dos próximos 60 dias (ainda dá tempo de vender seguro e hotel) ----
    limite = dt.datetime.combine(hoje, dt.time.min) + dt.timedelta(days=60)
    inicio = dt.datetime.combine(hoje, dt.time.min)
    viajantes_seg = {t['nome'].strip().lower() for t in vend if produto(t) == 'seguro'} | {chave_cliente(t) for t in vend if produto(t) == 'seguro'}
    proximas = []
    for t in vend:
        d = t.get('data_ida')
        if produto(t) == 'internacional' and d and inicio <= d <= limite:
            proximas.append(dict(nome=nome_curto(t['nome']), data=d, rota=t['ida'].strip(),
                                 seguro=t['nome'].strip().lower() in viajantes_seg or chave_cliente(t) in viajantes_seg))
    proximas.sort(key=lambda x: x['data'])
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
        categorias=categorias, faixas=faixas, em_risco=em_risco, penetracao=penetracao, proximas=proximas,
        clientes=clientes, lucro_cli=lucro_cli, seg_cli=seg_cli, recorrentes=recorrentes, sumidos=sumidos, unicos=unicos,
        sem_seguro=sem_seguro, melhores_margens=melhores_margens, ref=ref, sem_pag=(len(sem_pag), soma(sem_pag, 'valor')),
    )


# ---------- textos (Telegram, HTML) ----------
def sequencia(O, parcial, rotulo_fim, res, top_conta, R, brl, pct, meses_abrev, imgs, I=None):
    """Lista ordenada de ('texto', str) e ('imagem', (Path, legenda)) para enviar ao Telegram.
    Cada bloco começa com "Para quê": a decisão que aquele dado ajuda a tomar."""
    esc = html.escape
    para = lambda t: f'<i>Para quê: {t}</i>'
    c1 = O['clientes'][0]
    share1 = c1['lucro'] / O['lucro_cli']

    # ---- 1) resumo ----
    m1 = (f'<b>Agência do Futuro · até {rotulo_fim}</b>\n'
          + para('saber se o mês foi bom e quanto cada tipo de venda deixa.') + '\n\n'
          f'Passaram pela agência <b>{mil(O["V"])}</b> em {O["n"]} vendas (quase tudo vai direto para as cias aéreas). '
          f'O lucro bruto foi de <b>{mil(O["L"])}</b>, uns <b>{mil(O["L"] / O["n_meses"])} por mês</b>.\n'
          f'Depois de custos e comissões, o lucro do ano é <b>{brl(res)}</b> (média de {brl(res / O["n_meses"])}/mês).\n'
          f'Cada 10% a mais de bilhetes internacionais = <b>+{mil(O["l_inter"] * 0.1 / O["n_meses"])} por mês</b>.')

    # ---- 2) retorno por categoria ----
    tabcat = ['Categoria        Vendas  Lucro   % lucro  Por venda', '-' * 47]
    for x in O['categorias']:
        tabcat.append(f'{x["nome"]:<15} {x["n"]:>7} {mil(x["lucro"]).replace("R$ ", ""):>7} {pct(x["share"], 0):>7} {mil(x["por_venda"]).replace("R$ ", ""):>10}')
    cat = {x['nome']: x for x in O['categorias']}
    pen = O['penetracao']
    linhas2 = [f'<b>Retorno por categoria</b>\n' + para('decidir o que oferecer primeiro a cada cliente.'),
               '<pre>' + '\n'.join(tabcat) + '</pre>']
    pontos = []
    if 'Seguro' in cat and 'Passagem' in cat:
        pontos.append(f'• Seguro é só {pct(cat["Seguro"]["share"], 0)} do lucro, mas cada venda deixa {brl(cat["Seguro"]["por_venda"])}, '
                      f'contra {brl(cat["Passagem"]["por_venda"])} de uma passagem, e não depende de cia nem de estoque.')
    if 'Hotel' in cat:
        pontos.append(f'• Hotel é {pct(cat["Hotel"]["share"], 0)} do lucro ({cat["Hotel"]["clientes"]} clientes), com {brl(cat["Hotel"]["por_venda"])} por venda.')
    if pen['n']:
        pontos.append(f'• Dos <b>{pen["n"]}</b> clientes que compraram passagem internacional, só <b>{pen["hotel"]}</b> ({pct(pen["hotel"] / pen["n"], 0)}) '
                      f'compraram hotel com você e <b>{pen["seguro"]}</b> ({pct(pen["seguro"] / pen["n"], 0)}) compraram seguro. É aí que está a venda que ainda não aconteceu.')
    canais = [x for x in O['tipos'] if x['nome'].startswith('Internacional')]
    if canais:
        pontos.append('• Passagem internacional por canal (lucro por venda): ' + '; '.join(f'{esc(x["curto"].replace("Intern. ", ""))} {brl(x["por_venda"])} ({x["n"]} vendas)' for x in canais) + '.')
    linhas2.append('\n'.join(pontos))
    linhas2.append('<i>Nacional ou internacional pelo destino do voo. Milhas = contas com nome de pessoa e programas. Site da cia = compra direto na cia ou plataforma. '
                   'Consolidadora = Ancoradouro e KG Travel.</i>')
    m2cat = '\n\n'.join(linhas2)

    # ---- 3) clientes: quem dá mais retorno ----
    fx = O['faixas']
    tabc = ['Cliente          Lucro Comp. Últ. Falta', '-' * 41]
    for c in O['clientes'][:8]:
        falta = ' '.join({'seguro': 'S', 'hotel': 'H'}[f] for f in c['falta']) or '-'
        tabc.append(f'{curto(c)[:15]:<15} {mil(c["lucro"]).replace("R$ ", ""):>6} {c["n"]:>5} {meses_abrev[c["ultima"] - 1]:>4} {falta:>5}')
    m3 = (f'<b>Clientes: quem dá mais retorno</b>\n' + para('saber a quem dar mais atenção e o que oferecer a cada um.') + '\n\n'
          f'• <b>{fx["A"]["n"]} clientes</b> (faixa A) geram metade do lucro bruto ({mil(fx["A"]["lucro"])}). '
          f'Outros {fx["B"]["n"]} (faixa B) somam mais 30%. Os {fx["C"]["n"]} restantes (faixa C) ficam com 20%.\n'
          + (f'• O maior é a empresa <b>{esc(c1["nome"])}</b> (CNPJ {c1["cnpj"]}, {c1["pax"]} passageiros diferentes): {pct(share1, 0)} do lucro, {c1["n"]} compras.\n'
             if c1['empresa'] else f'• O maior é {esc(c1["nome"])}: {pct(share1, 0)} do lucro, {c1["n"]} compras.\n')
          + '\n<b>Faixa A, do maior para o menor</b>\n<pre>' + '\n'.join(tabc) + '</pre>\n'
          '<i>Falta: S = nunca comprou seguro com você, H = nunca comprou hotel (só para quem já viajou para fora).</i>')
    if O['em_risco']:
        m3 += ('\n\n<b>Clientes importantes que pararam de comprar</b> (faixa A ou B, sem compra há 3+ meses)\n'
               + '\n'.join(f'• {esc(c["nome"])}: {mil(c["lucro"])} de lucro, última compra em {meses_abrev[c["ultima"] - 1]}' for c in O['em_risco'][:5]))

    acoes = ['<b>O que fazer com cada grupo</b>']
    a_seg = [c for c in O['clientes'] if c['faixa'] in 'AB' and 'seguro' in c['falta']]
    if a_seg:
        acoes.append(f'1. <b>Faixa A/B sem seguro:</b> {", ".join(esc(c["nome"]) for c in a_seg[:5])}. Ofereça seguro na próxima cotação.')
    if c1['n'] >= 12:
        quem = f'a empresa {esc(c1["nome"])}, {c1["pax"]} passageiros' if c1['empresa'] else esc(c1['nome'])
        acoes.append(f'2. <b>Maior cliente</b> ({quem}, {pct(share1, 0)} do lucro): contrato com taxa de serviço mensal ou prioridade de atendimento. Um único cliente sustenta boa parte do resultado.')
    if O['em_risco']:
        acoes.append(f'3. <b>Faixa A/B parada:</b> são {len(O["em_risco"])} clientes sem comprar há 3+ meses (os 5 maiores estão listados acima). Chame primeiro os de maior lucro: cada um vale mais que uma venda nova.')
    acoes.append('4. <b>Faixa C:</b> atendimento no automático (mensagem padrão e link de cotação). O tempo vai para a faixa A.')
    acoes.append('5. <b>Antes de cada viagem:</b> chame 45 dias antes da data em que o cliente costuma viajar, com cotação pronta.')
    m3 += '\n\n' + '\n\n'.join(acoes)

    # ---- 4) próximas viagens ----
    m4 = ''
    if O['proximas']:
        sem = [x for x in O['proximas'] if not x['seguro']]
        linhas4 = [f'<b>Viagens internacionais dos próximos 60 dias</b>\n' + para('vender seguro, hotel e outros serviços antes de o cliente embarcar.') + '\n',
                   f'{len(O["proximas"])} passageiros viajam nos próximos 60 dias, e {len(sem)} ainda não têm seguro comprado com você.']
        linhas4 += [f'• {esc(x["nome"])}: {x["data"]:%d/%m}, {esc(x["rota"])}' + (' (já tem seguro)' if x['seguro'] else '') for x in O['proximas'][:10]]
        m4 = '\n'.join(linhas4)

    # ---- 5) oportunidades ----
    linhas = [f'<b>Onde dá para ganhar mais</b>\n' + para('escolher em quais ações gastar o seu tempo, pelo ganho estimado.') + '\n\n'
              f'Potencial estimado: <b>+{mil(O["total"])}</b> no período (≈ {mil(O["total"] / O["n_meses"])}/mês), somando as ideias abaixo. São estimativas, não promessas.\n']
    for i, o in enumerate(O['ops'], 1):
        linhas.append(f'<b>{i}. {esc(o["curto"])}</b> · +{mil(o["ganho"])} · esforço {o["esforco"].lower()}\n'
                      f'{esc(o["por_que"])}\n<i>Como:</i> {esc(o["passo"])}\n<i>{esc(o["premissa"])}</i>\n')
    m5 = '\n'.join(linhas)

    # ---- 6) produtos que ainda não vende ----
    serv = [x for x in O['categorias'] if x['nome'] == 'Outros serviços']
    m6 = ('<b>Produtos que você ainda não vende (ou vende pouco)</b>\n' + para('aumentar o lucro por cliente sem depender de vender mais bilhetes.') + '\n\n'
          'Na sua planilha aparecem passagem, hotel e seguro' + (f', e {serv[0]["n"]} vendas de outros serviços (como aluguel de carro e remarcação)' if serv else '') + '. '
          'O mercado de agências também vende: locação de carros, traslados e receptivo, ingressos e passeios, chip/eSIM internacional, '
          'cartão de viagem pré-pago (câmbio) e sala VIP. Pelas fontes que achei, a comissão de hotel, carro, traslado e pacote costuma ficar entre 5% e 15% do valor, '
          'e em ingressos e seguros pode ser um valor fixo por produto.\n\n'
          '1. <b>Traslado e receptivo no destino:</b> combina com os passageiros que viajam para fora (lista acima).\n'
          '2. <b>Aluguel de carro:</b> você já vendeu 1 (Localiza, via Ancoradouro).\n'
          '3. <b>Chip/eSIM e cartão de viagem pré-pago:</b> são vendidos junto com o seguro, na mesma conversa.\n'
          '4. <b>Ingressos e passeios:</b> para clientes que já reservaram hotel com você.\n'
          '5. <b>Taxa de remarcação e alteração:</b> já existe na sua planilha e deixou quase todo o valor como lucro. Cobrar por esse serviço, de forma padronizada, é um produto.\n\n'
          'Não achei percentuais públicos de comissão para chip, câmbio e sala VIP, então não estimei ganho. '
          '<b>Quais desses você já consegue comprar de um fornecedor?</b> Com a comissão real, eu calculo o ganho.\n'
          '<i>Fontes: <a href="https://monde.com.br/plano-de-comissao-receita/">Monde</a>, '
          '<a href="https://blog.inovvatur.com.br/post/como-calcular-comissao-agentes-viagens-2025/">Inovvatur</a>, '
          '<a href="https://www.panrotas.com.br/mercado/cartoes-de-assistencia/2026/09/seguro-viagem-protecao-para-o-viajante-receita-para-o-agente-veja-na-revista-panrotas_231705.html">Panrotas</a>.</i>')

    # ---- 7) retiradas ----
    m7 = ''
    if I:
        tot = I['total']
        tabr = ['Rota          Trechos    Valor    %', '-' * 34]
        for k, n, v in I['rotas'][:8]:
            tabr.append(f'{k.replace(" – ", "–"):<13} {n:>6} {mil(v).replace("R$ ", ""):>8} {pct(v / tot, 0):>4}')
        usados = sorted({c for k, _, _ in I['rotas'][:8] for c in k.split(' – ') if c in CIDADES})
        leg = ', '.join(f'{c} = {CIDADES[c]}' for c in usados)
        linhas7 = [f'<b>Suas retiradas em passagens</b>\n' + para('controlar quanto do seu direito sai em viagens e onde ele se concentra.') + '\n\n'
                   f'{brl(tot)} em {I["n"]} lançamentos (média de {brl(I["medio"])} por trecho)'
                   + (f', contra um direito de {brl(R["dir"])} no período' if R else '') + '.',
                   '<b>Por rota</b> (ida e volta somadas)\n<pre>' + '\n'.join(tabr) + '</pre>' + (f'\n<i>{esc(leg)}</i>' if leg else ''),
                   '<b>O que mais pesa</b>']
        pes = ', '.join(f'{esc(k)} {pct(v / tot, 0)}' for k, n, v in I['pessoas'])
        pontos7 = [f'• <b>Quem retira:</b> {pes}.']
        mes_pico = max(I['meses'], key=lambda m: I['meses'][m])
        top_mes = sorted([x for x in I['itens'] if x['data'].month == mes_pico], key=lambda x: -x['valor'])[:3]
        det = '; '.join((f'{x["rota"]} ' if rota_par(x['rota']) else 'sem rota informada ') + mil(x['valor']) for x in top_mes)
        pontos7.append(f'• <b>Mês mais pesado: {meses_abrev[mes_pico - 1]}</b> com {mil(I["meses"][mes_pico])} ({pct(I["meses"][mes_pico] / tot, 0)} do total). Maiores itens: {esc(det)}.')
        if I['sem_rota']:
            sr = sorted(I['sem_rota'], key=lambda x: -x['valor'])

            def _desc(x):
                d = ' '.join(t for t in (x['cia'], x['loc']) if t.strip() not in ('', '-'))
                return f'{x["data"]:%d/%m} {mil(x["valor"])} ({esc(d) if d else "sem descrição"})'
            pontos7.append(f'• <b>Sem rota ou destino no lançamento:</b> {len(sr)} lançamentos, {mil(sum(x["valor"] for x in sr))} ({pct(sum(x["valor"] for x in sr) / tot, 0)}): '
                           + '; '.join(_desc(x) for x in sr[:3]) + '. Sem rota, não consigo separar por destino. Me diga o que foram, ou preencha a rota na planilha.')
        if I['dobradas']:
            v_d = sum(y['valor'] for g in I['dobradas'] for y in g)
            pontos7.append(f'• <b>Mesmo voo, duas pessoas:</b> {len(I["dobradas"])} voos foram retirados para mais de uma pessoa na mesma data ({mil(v_d)} no total). É onde o valor retirado dobra sem mudar a rota.')
        pontos7.append('• <b>Companhia:</b> ' + ', '.join(f'{esc(k)} {pct(v / tot, 0)}' for k, v in I['cias'][:3]) + '.')
        if R:
            acima = [x for x in R['M'] if x['retirado'] > x['direito']]
            if acima:
                pontos7.append('• <b>Meses acima do direito:</b> ' + '; '.join(f'{x["label"]} (retirou {mil(x["retirado"])}, direito {mil(x["direito"])})' for x in acima)
                               + '. Seguem o agrupamento da planilha, que pode diferir da data da compra.')
        linhas7.append('\n'.join(pontos7))
        linhas7.append('<b>Para equilibrar</b>\n'
                       '1. Defina um teto mensal igual ao direito do mês (R$ 2.000 fixos + suas comissões). Viagens grandes, como as de julho, podem ser divididas em dois meses.\n'
                       '2. As rotas que você repete todo mês (as primeiras da tabela) são boas candidatas a emissão em milhas.\n'
                       '3. Decida se toda viagem precisa de retirada para as duas pessoas. É a forma mais rápida de reduzir o valor sem mudar as rotas.')
        m7 = '\n\n'.join(linhas7)

    aten = []
    if O['sem_pag'][0]:
        aten.append(f'• {O["sem_pag"][0]} vendas ({mil(O["sem_pag"][1])}) sem forma de pagamento anotada: confirme se o dinheiro entrou.')
    if top_conta:
        aten.append(f'• A conta "{esc(top_conta[0].title())}" emite {pct(top_conta[1] / O["V"], 0)} do volume. Se ela travar, o faturamento trava junto.')
    if R:
        aten.append(f'• Suas retiradas: {brl(R["ret"])} no ano, contra um direito de {brl(R["dir"])} (saldo acumulado {brl(R["fim"])}).')
    m8 = '<b>Atenção</b>\n' + para('conferir o que pode virar problema de caixa ou dependência.') + '\n\n' + '\n'.join(aten) if aten else ''

    seq = [('texto', m1), ('imagem', imgs['lucro']), ('texto', m2cat), ('imagem', imgs['categorias']),
           ('texto', m3), ('imagem', imgs['clientes'])]
    if m4:
        seq.append(('texto', m4))
    seq += [('texto', m5), ('imagem', imgs['oportunidades']), ('texto', m6)]
    if m7:
        seq += [('texto', m7), ('imagem', imgs['retiradas'])]
    if m8:
        seq.append(('texto', m8))
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


def graficos(O, out, sufixo, I=None):
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

    # 2) retorno por categoria (o que oferecer)
    ct = O['categorias'][::-1]
    fig, ax, plt = _base('Retorno por categoria', 'Barra = lucro bruto no período. Texto = vendas, lucro por venda e % do lucro')
    ys = list(range(len(ct)))
    ax.barh(ys, [x['lucro'] for x in ct], color=[ACCENT2 if x['nome'] == 'Seguro' else ACCENT for x in ct], height=0.62)
    ax.set_yticks(ys)
    ax.set_yticklabels([x['nome'] for x in ct], fontsize=9, color=INK)
    mx = max(x['lucro'] for x in ct)
    for y, x in zip(ys, ct):
        ax.text(x['lucro'] + mx * 0.015, y, f'{mil(x["lucro"])} · {x["n"]} vendas · R$ {x["por_venda"]:.0f} por venda · {_pct(x["share"])}', va='center', fontsize=8.5, color=INK)
    ax.set_xlim(0, mx * 2.7)
    ax.xaxis.set_visible(False)
    fig.subplots_adjust(top=0.80, bottom=0.05, left=0.19, right=0.98)
    imgs['categorias'] = (_salva(fig, plt, out, f'categorias-{sufixo}.png'), 'Retorno por categoria: passagem, hotel, seguro e outros serviços.')

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
    if I and I['rotas']:
        rt = I['rotas'][:8][::-1]
        fig, ax, plt = _base('Suas retiradas por rota', f'Barra = valor retirado (ida e volta somadas). Total: {mil(I["total"])}')
        ys = list(range(len(rt)))
        ax.barh(ys, [x[2] for x in rt], color=ACCENT, height=0.62)
        ax.set_yticks(ys)
        ax.set_yticklabels([x[0].replace(' – ', '–') for x in rt], fontsize=9, color=INK)
        mx = max(x[2] for x in rt)
        for y, x in zip(ys, rt):
            ax.text(x[2] + mx * 0.015, y, f'{mil(x[2])} · {x[1]} {"trecho" if x[1] == 1 else "trechos"} · {_pct(x[2] / I["total"])}', va='center', fontsize=8.5, color=INK)
        ax.set_xlim(0, mx * 1.7)
        ax.xaxis.set_visible(False)
        fig.subplots_adjust(top=0.80, bottom=0.05, left=0.19, right=0.98)
        imgs['retiradas'] = (_salva(fig, plt, out, f'retiradas-rotas-{sufixo}.png'), 'Retiradas em passagens por rota.')
    return imgs
