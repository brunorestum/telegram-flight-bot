"""Recebíveis do Pagar.me (API v5): o que ainda vai entrar no caixa e quando.

Só lê (GET /core/v5/payables). Precisa da variável PAGARME_API_KEY (chave secreta do Pagar.me).
Sem a chave, o bloco é omitido do relatório. Se a API responder erro, o relatório mostra o erro (sem a chave).

Pontos que a documentação pública não deixa claros e que este código NÃO assume:
- se `amount` já é líquido de taxa: o relatório mostra `amount` e `fee` separados e avisa para conferir no painel;
- quais valores de `status` existem: qualquer status diferente de "paid" com data de pagamento futura conta como "a receber",
  e o relatório lista os status que apareceram, para você conferir.
"""
import base64
import collections
import datetime as dt
import os

URL = 'https://api.pagar.me/core/v5/payables'
DIAS_A_FRENTE = 180
MAX_PAGINAS = 60


def _cabecalho():
    chave = os.environ['PAGARME_API_KEY'].strip()
    token = base64.b64encode(f'{chave}:'.encode()).decode()
    return {'Authorization': f'Basic {token}', 'Accept': 'application/json'}


def buscar(hoje):
    """Devolve (lista_de_recebiveis, None) ou (None, mensagem_de_erro). Nunca inclui a chave na mensagem."""
    import requests
    if not os.environ.get('PAGARME_API_KEY', '').strip():
        return None, 'a variável PAGARME_API_KEY não está definida neste terminal'
    params = {'payment_date_since': hoje.isoformat(), 'payment_date_until': (hoje + dt.timedelta(days=DIAS_A_FRENTE)).isoformat(), 'size': 100}
    itens, cursor = [], None
    for _ in range(MAX_PAGINAS):
        p = dict(params)
        if cursor:
            p['forward_cursor'] = cursor
        try:
            r = requests.get(URL, headers=_cabecalho(), params=p, timeout=60)
        except requests.RequestException as e:
            return None, f'falha de conexão ({type(e).__name__})'
        if r.status_code != 200:
            return None, f'HTTP {r.status_code}: {r.text[:200]}'
        j = r.json()
        dados = j.get('data', j) if isinstance(j, dict) else j
        if not dados:
            break
        itens += dados
        pg = (j.get('paging') or {}) if isinstance(j, dict) else {}
        prox = pg.get('forward_cursor') or pg.get('next')
        if not prox:
            break
        if isinstance(prox, str) and 'forward_cursor=' in prox:
            prox = prox.split('forward_cursor=')[1].split('&')[0]
        if prox == cursor:
            break
        cursor = prox
    return itens, None


def _data(txt):
    try:
        return dt.datetime.fromisoformat(str(txt).replace('Z', '+00:00')).date()
    except (ValueError, TypeError):
        return None


def analisar(itens, hoje):
    """Agrupa o que ainda não foi pago por janela e por mês. Valores da API vêm em centavos."""
    status = collections.Counter(str(x.get('status')) for x in itens)
    abertos = []
    for x in itens:
        d = _data(x.get('payment_date'))
        if d is None or d < hoje or str(x.get('status')).lower() == 'paid':
            continue
        abertos.append(dict(data=d, valor=(x.get('amount') or 0) / 100, taxa=(x.get('fee') or 0) / 100, parcela=x.get('installment')))
    janelas = {n: sum(a['valor'] for a in abertos if (a['data'] - hoje).days <= n) for n in (7, 30, 60, 90)}
    meses = collections.OrderedDict()
    for a in sorted(abertos, key=lambda a: a['data']):
        k = (a['data'].year, a['data'].month)
        m = meses.setdefault(k, dict(valor=0.0, taxa=0.0, n=0))
        m['valor'] += a['valor']
        m['taxa'] += a['taxa']
        m['n'] += 1
    metodos = collections.defaultdict(float)
    for x in itens:
        d = _data(x.get('payment_date'))
        if d is not None and d >= hoje and str(x.get('status')).lower() != 'paid':
            metodos[str(x.get('payment_method') or x.get('type') or '?')] += (x.get('amount') or 0) / 100
    por_dia = collections.defaultdict(float)
    for a in abertos:
        por_dia[a['data']] += a['valor']
    maior = max(por_dia.items(), key=lambda z: z[1]) if por_dia else None
    return dict(total_itens=len(itens), status=dict(status), abertos=len(abertos), total=sum(a['valor'] for a in abertos),
                taxa=sum(a['taxa'] for a in abertos), janelas=janelas, meses=meses, maior_dia=maior, metodos=dict(metodos))


def bloco(hoje, out, sufixo, brl, mil, meses_abrev):
    """Itens ('texto'|'imagem', conteúdo) para o Telegram. Lista vazia se PAGARME_API_KEY não estiver configurada."""
    if not os.environ.get('PAGARME_API_KEY'):
        return []
    cab = ('<b>A receber no Pagar.me</b>\n<i>Para quê: prever o caixa (quanto entra e quando) para planejar retiradas e pagamentos.</i>\n\n')
    itens, erro = buscar(hoje)
    if erro:
        return [('texto', cab + f'Não consegui ler o Pagar.me: {erro}\nConfira a chave e as permissões dela.')]
    A = analisar(itens, hoje)
    if not A['abertos']:
        return [('texto', cab + f'Nenhum recebível em aberto nos próximos {DIAS_A_FRENTE} dias. '
                              f'Status que apareceram: {A["status"] or "nenhum"}.')]
    j = A['janelas']
    linhas = [f'Total a receber nos próximos {DIAS_A_FRENTE} dias: <b>{brl(A["total"])}</b> em {A["abertos"]} recebíveis '
              f'(taxas previstas: {brl(A["taxa"])}).',
              f'• Próximos 7 dias: {brl(j[7])}\n• Próximos 30 dias: {brl(j[30])}\n• Próximos 60 dias: {brl(j[60])}\n• Próximos 90 dias: {brl(j[90])}']
    tab = ['Mês        Recebíveis    Valor', '-' * 29]
    for (ano, mes), m in A['meses'].items():
        tab.append(f'{meses_abrev[mes - 1]}/{str(ano)[2:]:<7} {m["n"]:>10} {mil(m["valor"]).replace("R$ ", ""):>8}')
    linhas.append('<pre>' + '\n'.join(tab) + '</pre>')
    if A['maior_dia']:
        linhas.append(f'Dia com maior entrada: {A["maior_dia"][0]:%d/%m}, {brl(A["maior_dia"][1])}.')
    linhas.append('<i>Valor = campo "amount" da API do Pagar.me. Na primeira vez, confira no painel do Pagar.me se ele já é líquido de taxa. '
                  f'Status que apareceram: {", ".join(f"{k} ({v})" for k, v in A["status"].items())}.</i>')
    seq = [('texto', cab + '\n\n'.join(linhas))]
    if len(A['meses']) >= 1:
        from oportunidades import ACCENT, _base, _pct, _salva
        fig, ax, plt = _base('Quanto entra por mês (Pagar.me)', f'Recebíveis em aberto nos próximos {DIAS_A_FRENTE} dias. Total: {mil(A["total"])}')
        xs = list(range(len(A['meses'])))
        vals = [m['valor'] for m in A['meses'].values()]
        ax.bar(xs, vals, color=ACCENT, width=0.62)
        for x, v in zip(xs, vals):
            ax.text(x, v + max(vals) * 0.02, mil(v).replace('R$ ', ''), ha='center', fontsize=8.5)
        ax.set_xticks(xs)
        ax.set_xticklabels([f'{meses_abrev[mes - 1]}/{str(ano)[2:]}' for (ano, mes) in A['meses']], fontsize=8.5)
        ax.set_ylim(0, max(vals) * 1.2)
        ax.yaxis.set_visible(False)
        fig.subplots_adjust(top=0.80, bottom=0.10, left=0.04, right=0.98)
        seq.append(('imagem', (_salva(fig, plt, out, f'pagarme-{sufixo}.png'), 'Recebíveis em aberto no Pagar.me, por mês.')))
    return seq
