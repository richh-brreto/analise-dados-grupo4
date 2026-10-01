"""
Gera graficos da sazonalidade aparente dos voos comerciais de passageiros a
partir de data/voos_brasil_paises_ingleses.csv (saida de filter_ingles.py).
O CSV ja contem apenas voos comerciais: os de carga/reabastecimento sao
descartados na etapa anterior.

Graficos gerados em graficos/ (PNG, 150 dpi):
  01_comercial_mensal.png          voos e passageiros por mes, com os meses de
                                   ferias escolares destacados
  02_sazonalidade_ano_a_ano.png    passageiros por mes do ano, uma linha por
                                   ano (2025 x 2026)
  03_sazonalidade_calendario.png   media mensal de voos e passageiros por
                                   temporada escolar e por estacao do ano
  04_passageiros_por_voo.png       media de passageiros por voo, mes a mes

O mes residual 2026-08 (2 voos que decolaram em 1o de agosto e vieram no
arquivo de julho, ver METODOLOGIA.md secao 4.3) e ignorado por padrao: nao
representa um mes completo e distorceria as series mensais e as medias.

Dependencia externa: matplotlib (pip install matplotlib). O restante e
biblioteca padrao.
"""
import csv
import os
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter, MaxNLocator

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
IN_PATH = os.path.join(BASE_DIR, "data", "voos_brasil_paises_ingleses.csv")
OUT_DIR = os.path.join(BASE_DIR, "graficos")
ENCODING = "latin-1"
DELIMITER = ";"

# Meses incompletos que nao entram nas series (ver METODOLOGIA.md, secao 4.3)
MESES_EXCLUIDOS = {(2026, 8)}

TEMPORADA_FERIAS = "férias escolares"
ORDEM_TEMPORADAS = [TEMPORADA_FERIAS, "volta às aulas", "período letivo"]
ORDEM_ESTACOES = ["verão", "outono", "inverno", "primavera"]
MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun",
               "jul", "ago", "set", "out", "nov", "dez"]

DESTINOS = "Brasil -> EUA, Canadá e Reino Unido"
FONTE = "Fonte: ANAC (dados combinados), tratados por scripts/filter_ingles.py"
ROTULO_SERIE = "voos comerciais de passageiros"

# --- Paleta -----------------------------------------------------------------
# Uma unica serie (voos comerciais) em azul; anos sao categorias ordenadas,
# em rampa de um unico matiz, claro -> escuro. Cores verificadas para
# daltonismo (deutan, protan e tritan) e para visao normal.
COR_SERIE = "#2a78d6"
COR_ANO = {2025: "#5598e7", 2026: "#104281"}
COR_FERIAS = "#cde2fb"         # fundo dos meses de ferias escolares

# Tons de interface (texto, eixos, grade) - nunca as cores das series
SUPERFICIE = "#fcfcfb"
TEXTO = "#0b0b0b"
TEXTO_2 = "#52514e"
TEXTO_SUAVE = "#898781"
GRADE = "#e1e0d9"
EIXO = "#c3c2b7"


def configurar_estilo():
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
        "figure.facecolor": SUPERFICIE,
        "axes.facecolor": SUPERFICIE,
        "savefig.facecolor": SUPERFICIE,
        "axes.edgecolor": EIXO,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": GRADE,
        "grid.linewidth": 0.8,
        "grid.linestyle": "-",
        "axes.axisbelow": True,
        "axes.titlelocation": "left",
        "axes.titlesize": 12,
        "axes.titleweight": "semibold",
        "axes.titlecolor": TEXTO,
        "axes.titlepad": 12,
        "axes.labelsize": 10,
        "axes.labelcolor": TEXTO_2,
        "xtick.color": EIXO,
        "ytick.color": EIXO,
        "xtick.labelcolor": TEXTO_2,
        "ytick.labelcolor": TEXTO_2,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.frameon": False,
        "legend.fontsize": 9,
        "legend.labelcolor": TEXTO_2,
        "figure.dpi": 100,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.25,
    })


# --- Leitura ----------------------------------------------------------------

def carregar_por_mes():
    """Le o CSV e devolve {(ano, mes): linha}, sem os meses excluidos."""
    por_mes = {}
    with open(IN_PATH, encoding=ENCODING, newline="") as f:
        for r in csv.DictReader(f, delimiter=DELIMITER):
            ano, mes = int(r["ano"]), int(r["mes"])
            if (ano, mes) in MESES_EXCLUIDOS:
                continue
            por_mes[(ano, mes)] = {
                "ano": ano,
                "mes": mes,
                "estacao": r["estacao"],
                "temporada": r["temporada"],
                "qtd_voos": int(r["qtd_voos"]),
                "nr_passageiros": int(r["nr_passageiros"]),
            }
    return por_mes


# --- Formatacao -------------------------------------------------------------

def fmt_int(v):
    """1234567 -> '1.234.567' (separador de milhar brasileiro)."""
    return f"{int(round(v)):,}".replace(",", ".")


def fmt_eixo(v, _pos=None):
    """Rotulos de eixo compactos: 2000000 -> '2 mi', 250000 -> '250 mil',
    1500 -> '1,5 mil'."""
    if v >= 1_000_000:
        if v % 1_000_000 == 0:
            return f"{v / 1e6:.0f} mi"
        return f"{v / 1e6:.1f} mi".replace(".", ",")
    if v >= 1000:
        if v % 1000 == 0:
            return f"{v / 1000:.0f} mil"
        return f"{v / 1000:.1f} mil".replace(".", ",")
    return f"{v:.0f}"


def rotulo_mes(ano, mes):
    return f"{MESES_ABREV[mes - 1]}/{ano % 100:02d}"


def rotulo_periodo(meses):
    (a0, m0), (a1, m1) = meses[0], meses[-1]
    return f"{MESES_ABREV[m0 - 1]}/{a0} a {MESES_ABREV[m1 - 1]}/{a1}"


# --- Utilitarios de desenho -------------------------------------------------

def titulo_figura(fig, texto):
    """Titulo geral alinhado a esquerda com o primeiro painel."""
    fig.canvas.draw()
    x0 = min(ax.get_position().x0 for ax in fig.axes)
    fig.suptitle(texto, x=x0, ha="left", fontsize=14, fontweight="semibold",
                 color=TEXTO)


def rodape(fig, texto=FONTE):
    fig.text(0.01, -0.02, texto, fontsize=8, color=TEXTO_SUAVE, ha="left",
             va="top")


def sombrear_ferias(ax, posicoes):
    """Faixas de fundo nas posicoes (indices no eixo x) de ferias escolares."""
    for p in posicoes:
        ax.axvspan(p - 0.5, p + 0.5, color=COR_FERIAS, alpha=0.6,
                   linewidth=0, zorder=0)


def linha_serie(ax, x, y, cor, rotulo=None):
    """Linha de 2px com marcadores contornados pela cor da superficie."""
    return ax.plot(x, y, color=cor, linewidth=2, solid_capstyle="round",
                   solid_joinstyle="round", marker="o", markersize=6,
                   markerfacecolor=cor, markeredgecolor=SUPERFICIE,
                   markeredgewidth=1.5, label=rotulo, zorder=3)[0]


def rotular_extremos(ax, x, y, fmt=fmt_int):
    """Rotula so o maior e o menor ponto da serie."""
    i_max = max(range(len(y)), key=lambda i: y[i])
    i_min = min(range(len(y)), key=lambda i: y[i])
    ax.annotate(fmt(y[i_max]), (x[i_max], y[i_max]), xytext=(0, 9),
                textcoords="offset points", ha="center", va="bottom",
                fontsize=9, color=TEXTO, fontweight="semibold")
    ax.annotate(fmt(y[i_min]), (x[i_min], y[i_min]), xytext=(0, -9),
                textcoords="offset points", ha="center", va="top",
                fontsize=9, color=TEXTO_2)


def eixo_meses(ax, meses):
    ax.set_xticks(range(len(meses)))
    ax.set_xticklabels([rotulo_mes(*m) for m in meses], rotation=45,
                       ha="right", rotation_mode="anchor")
    ax.set_xlim(-0.6, len(meses) - 0.4)
    ax.set_xlabel("Mês de partida")


def salvar(fig, nome):
    caminho = os.path.join(OUT_DIR, nome)
    fig.savefig(caminho)
    plt.close(fig)
    print(f"  gerado: {os.path.relpath(caminho, BASE_DIR)}")


# --- Graficos ---------------------------------------------------------------

def grafico_comercial_mensal(por_mes, meses):
    x = list(range(len(meses)))
    voos = [por_mes[m]["qtd_voos"] for m in meses]
    pax = [por_mes[m]["nr_passageiros"] for m in meses]
    ferias = [i for i, m in enumerate(meses)
              if por_mes[m]["temporada"] == TEMPORADA_FERIAS]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True,
                                   layout="constrained")
    paineis = [
        (ax1, voos, "Voos comerciais por mês", "Quantidade de voos"),
        (ax2, pax, "Passageiros em voos comerciais por mês", "Passageiros"),
    ]
    for ax, serie, titulo, ylabel in paineis:
        sombrear_ferias(ax, ferias)
        linha_serie(ax, x, serie, COR_SERIE)
        rotular_extremos(ax, x, serie)
        ax.set_title(titulo)
        ax.set_ylabel(ylabel)
        ax.set_ylim(0, max(serie) * 1.2)
        ax.yaxis.set_major_formatter(FuncFormatter(fmt_eixo))
    eixo_meses(ax2, meses)

    legenda = [
        Line2D([], [], color=COR_SERIE, linewidth=2, marker="o",
               markersize=6, markeredgecolor=SUPERFICIE, label=ROTULO_SERIE),
        Patch(facecolor=COR_FERIAS, label="mês de férias escolares"),
    ]
    ax1.legend(handles=legenda, loc="upper right", ncol=2)

    titulo_figura(fig, f"Voos comerciais mês a mês — {DESTINOS}")
    rodape(fig)
    salvar(fig, "01_comercial_mensal.png")


def grafico_sazonalidade_ano_a_ano(por_mes):
    por_ano = defaultdict(dict)
    for (ano, mes), l in por_mes.items():
        por_ano[ano][mes] = l["nr_passageiros"]
    meses_ferias = sorted({m for (_, m), l in por_mes.items()
                           if l["temporada"] == TEMPORADA_FERIAS})

    fig, ax = plt.subplots(figsize=(12, 5.5), layout="constrained")
    sombrear_ferias(ax, meses_ferias)
    maior = 0
    for ano in sorted(por_ano):
        xs = sorted(por_ano[ano])
        ys = [por_ano[ano][m] for m in xs]
        maior = max(maior, max(ys))
        linha_serie(ax, xs, ys, COR_ANO[ano], rotulo=str(ano))
        ax.annotate(str(ano), (xs[-1], ys[-1]), xytext=(9, 0),
                    textcoords="offset points", va="center", ha="left",
                    fontsize=9, fontweight="semibold", color=TEXTO_2)

    ax.set_title("Sazonalidade dos passageiros em voos comerciais — "
                 f"{DESTINOS}, ano a ano")
    ax.set_xlabel("Mês do ano")
    ax.set_ylabel("Passageiros em voos comerciais")
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels([m.capitalize() for m in MESES_ABREV])
    ax.set_xlim(0.5, 12.9)
    ax.set_ylim(0, maior * 1.18)
    ax.yaxis.set_major_formatter(FuncFormatter(fmt_eixo))
    handles, labels = ax.get_legend_handles_labels()
    handles.append(Patch(facecolor=COR_FERIAS, label="mês de férias escolares"))
    ax.legend(handles=handles, loc="upper right", ncol=len(handles),
              title="Ano da partida", title_fontsize=9)
    rodape(fig)
    salvar(fig, "02_sazonalidade_ano_a_ano.png")


def media_por_categoria(por_mes, campo, ordem):
    """Media mensal de voos e passageiros por valor de `campo`."""
    grupos = defaultdict(list)
    for l in por_mes.values():
        grupos[l[campo]].append(l)
    resultado = []
    for cat in ordem:
        ls = grupos.get(cat, [])
        if not ls:
            continue
        n = len(ls)
        resultado.append({
            "categoria": cat,
            "n_meses": n,
            "voos": sum(l["qtd_voos"] for l in ls) / n,
            "pax": sum(l["nr_passageiros"] for l in ls) / n,
        })
    return resultado


def barras_media(ax, dados, chave, ylabel, titulo):
    cats = [f"{d['categoria']}\n({d['n_meses']} meses)" for d in dados]
    vals = [d[chave] for d in dados]
    barras = ax.bar(cats, vals, width=0.42, color=COR_SERIE,
                    edgecolor=SUPERFICIE, linewidth=1.5)
    for b, v in zip(barras, vals):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height(), fmt_int(v),
                ha="center", va="bottom", fontsize=9, color=TEXTO,
                fontweight="semibold", clip_on=False)
    ax.set_title(titulo)
    ax.set_ylabel(ylabel)
    ax.set_ylim(0, max(vals) * 1.18)
    ax.yaxis.set_major_formatter(FuncFormatter(fmt_eixo))
    ax.tick_params(axis="x", length=0)


def grafico_sazonalidade_calendario(por_mes):
    por_temporada = media_por_categoria(por_mes, "temporada", ORDEM_TEMPORADAS)
    por_estacao = media_por_categoria(por_mes, "estacao", ORDEM_ESTACOES)

    fig, axes = plt.subplots(2, 2, figsize=(13, 8.5), layout="constrained")
    barras_media(axes[0][0], por_temporada, "voos",
                 "Média mensal de voos", "Voos por temporada escolar")
    barras_media(axes[0][1], por_estacao, "voos",
                 "Média mensal de voos", "Voos por estação do ano")
    barras_media(axes[1][0], por_temporada, "pax",
                 "Média mensal de passageiros",
                 "Passageiros por temporada escolar")
    barras_media(axes[1][1], por_estacao, "pax",
                 "Média mensal de passageiros",
                 "Passageiros por estação do ano")
    axes[1][0].set_xlabel("Temporada (calendário escolar brasileiro)")
    axes[1][1].set_xlabel("Estação do ano (hemisfério sul)")

    titulo_figura(fig, "Sazonalidade aparente dos voos comerciais — "
                       f"{DESTINOS}, médias mensais")
    rodape(fig, FONTE + ". Médias calculadas sobre os meses completos de cada "
                "categoria; o número de meses aparece entre parênteses.")
    salvar(fig, "03_sazonalidade_calendario.png")
    return por_temporada, por_estacao


def grafico_passageiros_por_voo(por_mes, meses):
    x = list(range(len(meses)))
    media = [por_mes[m]["nr_passageiros"] / por_mes[m]["qtd_voos"]
             for m in meses]
    ferias = [i for i, m in enumerate(meses)
              if por_mes[m]["temporada"] == TEMPORADA_FERIAS]

    fig, ax = plt.subplots(figsize=(13, 5), layout="constrained")
    sombrear_ferias(ax, ferias)
    linha_serie(ax, x, media, COR_SERIE)
    rotular_extremos(ax, x, media, fmt=lambda v: f"{v:.0f}")
    ax.set_title(f"Média de passageiros por voo comercial — {DESTINOS}")
    ax.set_ylabel("Passageiros por voo")
    folga = (max(media) - min(media)) * 0.6
    ax.set_ylim(min(media) - folga, max(media) + folga)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, steps=[1, 2, 5, 10]))
    eixo_meses(ax, meses)
    ax.legend(handles=[Patch(facecolor=COR_FERIAS,
                             label="mês de férias escolares")],
              loc="upper right")
    rodape(fig, FONTE + ". Eixo vertical não começa em zero, para evidenciar "
                "a variação.")
    salvar(fig, "04_passageiros_por_voo.png")


# --- Resumo no console ------------------------------------------------------

def imprimir_resumo(por_mes, meses, por_temporada, por_estacao):
    tot_voos = sum(l["qtd_voos"] for l in por_mes.values())
    tot_pax = sum(l["nr_passageiros"] for l in por_mes.values())

    print(f"\nPeriodo analisado: {rotulo_periodo(meses)} ({len(meses)} meses)")
    if MESES_EXCLUIDOS:
        print("Meses ignorados (residuais): "
              + ", ".join(rotulo_mes(a, m) for a, m in sorted(MESES_EXCLUIDOS)))
    print(f"Voos comerciais: {fmt_int(tot_voos)} voos, "
          f"{fmt_int(tot_pax)} passageiros "
          f"({tot_pax / tot_voos:.0f} passageiros por voo)")

    pax_mes = sorted(meses, key=lambda m: por_mes[m]["nr_passageiros"])
    print(f"Mes com mais passageiros:  {rotulo_mes(*pax_mes[-1])} "
          f"({fmt_int(por_mes[pax_mes[-1]]['nr_passageiros'])})")
    print(f"Mes com menos passageiros: {rotulo_mes(*pax_mes[0])} "
          f"({fmt_int(por_mes[pax_mes[0]]['nr_passageiros'])})")

    print("\nMedia mensal por temporada escolar:")
    for d in por_temporada:
        print(f"  {d['categoria']:<18} {fmt_int(d['voos']):>6} voos  "
              f"{fmt_int(d['pax']):>8} passageiros  ({d['n_meses']} meses)")
    print("Media mensal por estacao do ano:")
    for d in por_estacao:
        print(f"  {d['categoria']:<18} {fmt_int(d['voos']):>6} voos  "
              f"{fmt_int(d['pax']):>8} passageiros  ({d['n_meses']} meses)")


def main():
    if not os.path.isfile(IN_PATH):
        raise SystemExit(f"Arquivo nao encontrado: {IN_PATH}\n"
                         "Rode antes: python scripts/filter_ingles.py")
    os.makedirs(OUT_DIR, exist_ok=True)
    configurar_estilo()

    por_mes = carregar_por_mes()
    meses = sorted(por_mes)

    print(f"Lendo {os.path.relpath(IN_PATH, BASE_DIR)}: {len(por_mes)} meses\n")
    grafico_comercial_mensal(por_mes, meses)
    grafico_sazonalidade_ano_a_ano(por_mes)
    por_temporada, por_estacao = grafico_sazonalidade_calendario(por_mes)
    grafico_passageiros_por_voo(por_mes, meses)

    imprimir_resumo(por_mes, meses, por_temporada, por_estacao)
    print(f"\nGraficos salvos em {os.path.relpath(OUT_DIR, BASE_DIR)}/")


if __name__ == "__main__":
    main()
