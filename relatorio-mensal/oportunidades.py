"""Oportunidades de lucro, textos curtos e gráficos em imagem (PNG) para o Telegram.

A agência é intermediária: quase todo o dinheiro que passa vai para a companhia aérea.
O que importa é a margem sobre esse volume (o quanto fica de cada R$ 100 vendidos).
Margem da venda = Base do imposto + Lucro não tributado + Comissão (a mesma "Receita da agência" do painel).
"""
import collections
import html

NACIONAIS = {'GOL', 'LATAM', 'AZUL'}
PISO_EMISSAO = 100.0      # lucro mínimo desejado por emissão pequena (R$)
CORTE_GRANDE = 5000.0     # venda a partir daqui é "grande"
PISO_GRANDE = 0.05        # margem mínima desejada nas vendas grandes
ADESAO_SEGURO = 0.15      # premissa de mercado: 15% dos clientes internacionais levam seguro
PREMIO_SEGURO = 300.0     # premissa: prêmio médio de R$ 300
COMISSAO_SEGURO = 0.25    # comissão de seguro viagem: 20% a 30% do prêmio (média de mercado)


def nome_cia(k):
    """'UNITED/ AIR CANADA' -> 'United'; 'KLM' -> 'KLM'."""
    w = k.split('/')[0].split()[0] if k.strip() else 'Sem cia'
    return w.upper() if len(w) <= 3 else w.title()


def margem_venda(t):
    return t['base'] + t['naotrib'] + t['com']


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
    V = sum(t['valor'] for t in vend)
    L = sum(margem_venda(t) for t in vend)
    take = L / V

    mes = []
    for m in M:
        g = [t for t in vend if t['mes'] == m['m']]
        v, l = sum(t['valor'] for t in g), sum(margem_venda(t) for t in g)
        mes.append(dict(label=m['label'], vendas=v, margem_rs=l, margem=l / v if v else 0, n=len(g)))

    por_cia = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for t in vend:
        k = (t['cia'] or 'SEM CIA').upper().strip()
        x = por_cia[k]
        x[0] += 1
        x[1] += t['valor']
        x[2] += margem_venda(t)
    cias = sorted(([k, x[0], x[1], x[2], x[2] / x[1]] for k, x in por_cia.items()), key=lambda z: -z[2])

    # cias que puxam a margem para baixo: muito volume, pouca margem
    baixas = [c for c in cias[:10] if c[4] < take * 0.5]
    vol_baixas = sum(c[2] for c in baixas)
    mar_baixas = sum(c[3] for c in baixas)

    ops = []

    # 1) piso por emissão pequena
    peq = [t for t in vend if t['valor'] < CORTE_GRANDE and margem_venda(t) < PISO_EMISSAO]
    falta = sum(PISO_EMISSAO - margem_venda(t) for t in peq)
    ganho = falta * 0.5
    ops.append(dict(
        chave='piso', curto='Piso de lucro por emissão', titulo=f'Piso de {brl(PISO_EMISSAO).replace(",00", "")} de lucro por emissão', ganho=ganho, esforco='Baixo',
        por_que=f'{len(peq)} das {len(vend)} vendas ({pct(len(peq) / len(vend), 0)}) deixaram menos de {brl(PISO_EMISSAO).replace(",00", "")} para a agência. '
                f'Emitir dá o mesmo trabalho com R$ 30 ou com R$ 300 de lucro.',
        passo='Cobrar uma taxa de emissão/serviço (ou arredondar o preço para cima) até o lucro chegar no piso. '
              'Comece pelos clientes novos e pelas emissões avulsas.',
        premissa=f'Estimativa considerando que só metade dos casos aceite ({mil(falta)} se todos aceitassem).'))

    # 2) piso de margem nas vendas grandes
    grandes = [t for t in vend if t['valor'] >= CORTE_GRANDE and margem_venda(t) / t['valor'] < PISO_GRANDE]
    ganho_g = sum(PISO_GRANDE * t['valor'] - margem_venda(t) for t in grandes)
    vol_g = sum(t['valor'] for t in grandes)
    mar_g = sum(margem_venda(t) for t in grandes)
    ops.append(dict(
        chave='grandes', curto='Margem mínima nas vendas grandes', titulo=f'Margem mínima de {pct(PISO_GRANDE, 0)} nas vendas grandes', ganho=ganho_g, esforco='Médio',
        por_que=f'{len(grandes)} vendas acima de {brl(CORTE_GRANDE).replace(",00", "")} movimentaram {mil(vol_g)} e deixaram só {pct(mar_g / vol_g)} '
                f'(a média da agência é {pct(take)}). Venda grande imobiliza caixa e cartão, e paga pouco pelo risco.',
        passo='Só fechar venda grande abaixo do piso se o cliente for recorrente ou a venda trouxer hotel/seguro junto. '
              'Se a cia é sempre a mesma, negociar taxa fixa por bilhete.',
        premissa='Estimativa: supõe que os clientes aceitem pagar o piso, sem perder a venda.'))

    # 3) cartão parcelado
    cart = [t for t in vend if 'cart' in t['pag'].lower()]
    pix = [t for t in vend if 'pix' in t['pag'].lower() and 'cart' not in t['pag'].lower()]
    mg = lambda g: (sum(margem_venda(t) for t in g) / sum(t['valor'] for t in g)) if g else 0
    Vc = sum(t['valor'] for t in cart)
    if cart:
        ops.append(dict(
            chave='cartao', curto='Taxa no cartão parcelado', titulo='Repassar 1 ponto de taxa nas vendas no cartão', ganho=Vc * 0.01, esforco='Médio',
            por_que=f'{len(cart)} vendas no cartão ({mil(Vc)}) ficam com {pct(mg(cart))} de margem'
                    + (f'; no pix, com {pct(mg(pix))}.' if pix else '.') + ' A taxa do cartão sai do lucro da agência.',
            passo='Tabela simples: à vista no pix = preço base; cartão = preço base + taxa do parcelamento. Ou dar desconto no pix.',
            premissa='Estimativa: 1 ponto percentual a mais sobre todo o volume no cartão do período.'))

    # 4) seguro viagem nos clientes internacionais
    inter = [t for t in vend if (t['cia'] or '').upper().strip() not in NACIONAIS]
    ganho_s = len(inter) * ADESAO_SEGURO * PREMIO_SEGURO * COMISSAO_SEGURO
    ops.append(dict(
        chave='seguro', curto='Seguro viagem', titulo='Vender seguro viagem junto com o bilhete internacional', ganho=ganho_s, esforco='Baixo',
        por_que=f'{len(inter)} vendas foram de outras cias (fora GOL/LATAM/AZUL), em geral viagens ao exterior, onde seguro é quase obrigatório. '
                'Hoje a agência não ganha nada com isso.',
        passo='Oferecer o seguro na hora de fechar a passagem, com um parceiro que pague comissão de 20% a 30% do prêmio.',
        premissa=f'Premissa de mercado, não da sua planilha: {pct(ADESAO_SEGURO, 0)} de adesão, prêmio de {brl(PREMIO_SEGURO).replace(",00", "")}, comissão de {pct(COMISSAO_SEGURO, 0)}.'))

    ops.sort(key=lambda o: -o['ganho'])
    total = sum(o['ganho'] for o in ops)

    return dict(
        V=V, L=L, take=take, n_meses=n_meses, n=len(vend), mes=mes, cias=cias, baixas=baixas,
        vol_baixas=vol_baixas, mar_baixas=mar_baixas, ops=ops, total=total, por_venda=L / len(vend),
        sem_pag=(len(sem_pag), sum(t['valor'] for t in sem_pag)),
        Vc=Vc, mg_cart=mg(cart), mg_pix=mg(pix), n_peq=len(peq),
    )


# ---------- textos (Telegram, HTML) ----------
def mensagens(O, M, parcial, rotulo_fim, res, top_conta, R, brl, pct):
    esc = html.escape
    fim, melhor = O['mes'][-1], max(O['mes'], key=lambda x: x['margem'])
    tend = ''
    if len(O['mes']) > 1 and fim['margem'] < melhor['margem'] - 0.005:
        tend = (f'\nA margem caiu de <b>{pct(melhor["margem"])}</b> ({melhor["label"]}) para <b>{pct(fim["margem"])}</b> ({fim["label"]}). ')
        if O['baixas']:
            nomes = ', '.join(nome_cia(c[0]) for c in O['baixas'][:3])
            tend += (f'As cias {esc(nomes)} movimentam {pct(O["vol_baixas"] / O["V"], 0)} do volume e deixam só {pct(O["mar_baixas"] / O["vol_baixas"])}: '
                     'muito dinheiro passando, pouco ficando.')
    m1 = (f'<b>Agência do Futuro · até {rotulo_fim}</b>\n'
          f'Passaram pela agência <b>{mil(O["V"])}</b> em {O["n"]} vendas (quase tudo vai para as companhias aéreas). '
          f'Ficaram <b>{mil(O["L"])}</b> antes de custos: <b>{brl(O["take"] * 100).replace(",00", "")} de cada R$ 100</b>, ou {brl(O["por_venda"])} por venda.\n'
          f'Depois de custos e comissões, o lucro do ano é <b>{brl(res)}</b> (média de {brl(res / O["n_meses"])}/mês).'
          + tend)

    linhas = [f'<b>Onde dá para ganhar mais</b>\nPotencial estimado: <b>+{mil(O["total"])}</b> no período (≈ {mil(O["total"] / O["n_meses"])}/mês), '
              'somando as ideias abaixo. São estimativas, não promessas.\n']
    for i, o in enumerate(O['ops'], 1):
        linhas.append(f'<b>{i}. {esc(o["titulo"])}</b> · +{mil(o["ganho"])} · esforço {o["esforco"].lower()}\n'
                      f'{esc(o["por_que"])}\n<i>Como:</i> {esc(o["passo"])}\n<i>{esc(o["premissa"])}</i>\n')
    m2 = '\n'.join(linhas)

    tab = ['Cia            Vendido  Margem', '-' * 31]
    for c in O['cias'][:8]:
        tab.append(f'{nome_cia(c[0]):<13} {mil(c[2]).replace("R$ ", ""):>8}  {pct(c[4]):>6}')
    tab.append(f'{"Total":<13} {mil(O["V"]).replace("R$ ", ""):>8}  {pct(O["take"]):>6}')
    m3 = '<b>Margem por companhia</b> (do que passa, quanto fica)\n<pre>' + '\n'.join(tab) + '</pre>'

    aten = []
    if O['sem_pag'][0]:
        aten.append(f'• {O["sem_pag"][0]} vendas ({mil(O["sem_pag"][1])}) sem forma de pagamento anotada: confirme se o dinheiro entrou.')
    if top_conta:
        aten.append(f'• A conta "{esc(top_conta[0].title())}" emite {pct(top_conta[1] / O["V"], 0)} do volume da agência. Se ela travar, o faturamento trava junto.')
    if R:
        aten.append(f'• Suas retiradas: {brl(R["ret"])} no ano, contra um direito de {brl(R["dir"])} (saldo acumulado {brl(R["fim"])}).')
    m4 = '<b>Atenção</b>\n' + '\n'.join(aten) if aten else ''
    return [m for m in (m1, m2, m3, m4) if m]


# ---------- gráficos (PNG) ----------
INK, MUTED, GRID, ACCENT, ALERT = '#1f2933', '#6b7785', '#e3e7ec', '#2f6fdb', '#c9541d'


def _base(titulo, sub):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'text.color': INK, 'axes.edgecolor': GRID})
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


def graficos(O, out, sufixo):
    """Retorna [(caminho, legenda)]."""
    imgs = []

    # 1) margem por mês
    fig, ax, plt = _base('Quanto fica de cada R$ 100 vendidos', 'Margem da agência por mês, antes de custos fixos e comissões')
    xs = list(range(len(O['mes'])))
    ys = [m['margem'] * 100 for m in O['mes']]
    ax.plot(xs, ys, color=ACCENT, linewidth=2, marker='o', markersize=6, markeredgecolor='white', markeredgewidth=1.5)
    ax.axhline(O['take'] * 100, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
    ax.text(len(xs) - 0.6, O['take'] * 100, f'média {_pct(O["take"])}', color=MUTED, fontsize=8.5, va='bottom', ha='right')
    for i in {0, len(xs) - 1, ys.index(max(ys)), ys.index(min(ys))}:
        baixo = i == ys.index(min(ys))
        ax.annotate(_pct(ys[i] / 100), (xs[i], ys[i]), textcoords='offset points', xytext=(0, -17 if baixo else 9),
                    ha='center', fontsize=9, color=INK)
    ax.set_xticks(xs)
    ax.set_xticklabels([m['label'] for m in O['mes']], fontsize=8.5)
    ax.set_ylim(0, max(ys) * 1.25)
    ax.yaxis.set_major_formatter(lambda v, _: f'{v:.0f}%')
    ax.grid(axis='y', color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    fig.subplots_adjust(top=0.78, bottom=0.11, left=0.08, right=0.97)
    p = out / f'margem-mensal-{sufixo}.png'
    fig.savefig(p)
    plt.close(fig)
    imgs.append((p, 'Margem por mês: de cada R$ 100 vendidos, quanto fica na agência.'))

    # 2) margem por cia
    top = O['cias'][:8][::-1]
    fig, ax, plt = _base('Margem por companhia aérea', 'Barra = margem. Texto = quanto passou pela agência. Laranja = abaixo da média')
    ys = list(range(len(top)))
    cores = [ACCENT if c[4] >= O['take'] else ALERT for c in top]
    ax.barh(ys, [c[4] * 100 for c in top], color=cores, height=0.62)
    ax.axvline(O['take'] * 100, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
    ax.text(O['take'] * 100, len(top) - 0.35, f'média {_pct(O["take"])}', ha='center', va='bottom', fontsize=8.5, color=MUTED)
    ax.set_yticks(ys)
    ax.set_yticklabels([nome_cia(c[0]) for c in top], fontsize=9, color=INK)
    mx = max(c[4] for c in top) * 100
    for y, c in zip(ys, top):
        ax.text(c[4] * 100 + mx * 0.015, y, f'{_pct(c[4])} · {mil(c[2])}', va='center', fontsize=8.5, color=INK,
                bbox=dict(facecolor='white', edgecolor='none', pad=1.5), zorder=5)
    ax.set_xlim(0, mx * 1.55)
    ax.xaxis.set_visible(False)
    ax.set_ylim(-0.6, len(top) - 0.1)
    fig.subplots_adjust(top=0.78, bottom=0.05, left=0.22, right=0.97)
    p = out / f'margem-cias-{sufixo}.png'
    fig.savefig(p)
    plt.close(fig)
    imgs.append((p, 'Margem por companhia. Laranja = abaixo da média da agência.'))

    # 3) oportunidades
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
    fig.subplots_adjust(top=0.78, bottom=0.05, left=0.42, right=0.97)
    p = out / f'oportunidades-{sufixo}.png'
    fig.savefig(p)
    plt.close(fig)
    imgs.append((p, 'Ganho estimado por oportunidade (estimativas).'))
    return imgs
