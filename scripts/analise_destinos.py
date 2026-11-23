"""
Ferias ou destino? Testes do grupo de comparacao (voos para destinos nao
anglofonos) contra a busca por curso de ingles, e graficos para a apresentacao.

Entrada: data/gold/{comparacao_destinos_semanal,correlacoes_destinos,parciais_destinos}
Saida:   graficos/comparacao_destinos/*.png e graficos/comparacao_destinos/resultados.json

Uso:
  python scripts/analise_destinos.py

So semanas completas. P-valores pelo tamanho efetivo da amostra, como em
analise_hipoteses.py (METODOLOGIA.md, secao 12).
"""
import json
import os
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analise_hipoteses import (AZUL, LARANJA, VERDE_AGUA, TINTA, TINTA2, MUDO, BASE, SUPERFICIE,
                               r_p_efetivo, eixo_datas)

warnings.filterwarnings("ignore")

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
GOLD = os.path.join(BASE_DIR, "data", "gold")
SAIDA = os.path.join(BASE_DIR, "graficos", "comparacao_destinos")
AMARELO = "#eda100"

SEG = {"anglofono": ("Anglófonos (EUA, Canadá, Reino Unido)", AZUL),
       "nao_anglofono": ("Não anglófonos (todos)", LARANJA),
       "nao_anglofono_america_sul": ("Não anglófonos: América do Sul", VERDE_AGUA),
       "nao_anglofono_europa": ("Não anglófonos: Europa", AMARELO)}


def ler(nome):
    return pd.read_csv(os.path.join(GOLD, nome, f"{nome}_parte0001.csv"), sep=";")


def salvar(fig, nome):
    os.makedirs(SAIDA, exist_ok=True)
    fig.savefig(os.path.join(SAIDA, nome), dpi=150, bbox_inches="tight")
    plt.close(fig)


def r2(y, *xs):
    X = np.column_stack([np.ones(len(y))] + list(xs))
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    return float(1 - res.var() / y.var())


def main():
    sem = ler("comparacao_destinos_semanal")
    sem["semana_inicio"] = pd.to_datetime(sem.semana_inicio)
    sem = sem[sem.semana_completa]
    larga = sem.pivot(index="semana_inicio", columns="segmento", values="nr_passageiros")
    part = sem.pivot(index="semana_inicio", columns="segmento", values="participacao_pax")
    tr = sem[sem.segmento == "anglofono"].set_index("semana_inicio")[
        ["tr_curso_ingles", "tr_curso_online", "tr_razao_ingles_curso_online", "temporada", "mes_referencia"]]
    corr = ler("correlacoes_destinos")
    parc = ler("parciais_destinos")
    R = {}

    # T1: cada segmento contra a busca, com defasagem
    R["t1_pico_por_segmento"] = {}
    for seg in ["anglofono", "nao_anglofono", "nao_anglofono_america_sul", "nao_anglofono_europa",
                "nao_anglofono_america_cn", "nao_anglofono_outros", "internacional"]:
        g = corr[(corr.segmento == seg) & (corr.serie_voos == "nr_passageiros") &
                 (corr.serie_trends == "tr_curso_ingles") & (corr.transformacao == "nivel")]
        g = g.set_index("defasagem_semanas")
        k = int(g.pearson.idxmax())
        R["t1_pico_por_segmento"][seg] = {
            "mesma_semana": r_p_efetivo(larga[seg], tr.tr_curso_ingles),
            "defasagem_pico": k,
            "pico": r_p_efetivo(larga[seg], tr.tr_curso_ingles.shift(-k))}

    # T2: parciais (tabela gold)
    p = parc[parc.serie_trends == "tr_curso_ingles"]
    R["t2_parciais"] = {f"{e}|{c}": {int(r.defasagem_semanas): [r.pearson_parcial, bool(r.significativo)]
                                     for r in g.itertuples()}
                        for (e, c), g in p.groupby(["explicativa", "controle"])}

    # T3: participacao anglofona no total internacional
    R["t3_participacao_anglofona"] = {
        "media_pct": round(float(part.anglofono.mean()), 2),
        "min_pct": round(float(part.anglofono.min()), 2),
        "max_pct": round(float(part.anglofono.max()), 2),
        "por_defasagem": {k: r_p_efetivo(part.anglofono, tr.tr_curso_ingles.shift(-k)) for k in range(0, 7)},
        "volume_internacional_defasagem3": r_p_efetivo(larga.internacional, tr.tr_curso_ingles.shift(-3)),
    }

    # T4: quanto da busca 3 semanas depois cada lado explica (R2)
    d = pd.DataFrame({"y": tr.tr_curso_ingles.shift(-3), "a": larga.anglofono,
                      "n": larga.nao_anglofono}).dropna()
    z = lambda s: (s - s.mean()) / s.std()
    R["t4_r2_defasagem3"] = {
        "so_anglofono": round(r2(d.y.values, z(d.a).values), 3),
        "so_nao_anglofono": round(r2(d.y.values, z(d.n).values), 3),
        "os_dois": round(r2(d.y.values, z(d.a).values, z(d.n).values), 3),
        "correlacao_entre_anglofono_e_nao": round(float(np.corrcoef(d.a, d.n)[0, 1]), 3),
    }

    # T5: perfil por temporada de cada segmento (100 = media do segmento)
    perfil = {}
    for seg in ["anglofono", "nao_anglofono", "nao_anglofono_america_sul", "nao_anglofono_europa",
                "nao_anglofono_america_cn"]:
        s = larga[seg]
        perfil[seg] = (s.groupby(tr.temporada).mean() / s.mean() * 100).round(1).to_dict()
    R["t5_perfil_temporada"] = perfil

    os.makedirs(SAIDA, exist_ok=True)
    with open(os.path.join(SAIDA, "resultados.json"), "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=2, default=str)
    graficos(larga, part, tr, corr, parc, R)
    for k, v in R.items():
        print(k, json.dumps(v, ensure_ascii=False, default=str)[:900])


def graficos(larga, part, tr, corr, parc, R):
    # 01: quatro segmentos x busca, pequenos multiplos
    fig, axes = plt.subplots(2, 2, figsize=(12, 6.4), sharex=True, sharey=True)
    for ax, (seg, (nome, cor)) in zip(axes.flat, SEG.items()):
        s = 100 * larga[seg] / larga[seg].max()
        ax.plot(s.index, s, color=cor, lw=2, label="passageiros (índice)")
        ax.plot(tr.index, tr.tr_curso_ingles, color=TINTA2, lw=1.4, ls=(0, (4, 2)),
                label='busca "curso de inglês"')
        for d, l in tr[tr.temporada == "férias escolares"].iterrows():
            ax.axvspan(d, d + pd.Timedelta(days=7), color="#f0efec", lw=0, zorder=0)
        pico = R["t1_pico_por_segmento"][seg]
        ax.set_title(f"{nome}\nPearson: {pico['mesma_semana']['r']:+.2f} na mesma semana, "
                     f"{pico['pico']['r']:+.2f} com {pico['defasagem_pico']:+d} sem.", fontsize=10)
        ax.set_ylim(30, 105)
        eixo_datas(ax, s.index.to_series())
    axes[0, 0].legend(loc="lower left", fontsize=8)
    axes[0, 0].set_ylabel("índice (100 = maior semana)")
    axes[1, 0].set_ylabel("índice (100 = maior semana)")
    fig.suptitle("Passageiros por grupo de destino × busca por curso de inglês (faixas: férias escolares)",
                 fontweight="bold", color=TINTA)
    salvar(fig, "01_segmentos_x_busca.png")

    # 02: correlogramas por segmento
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ks = list(range(-8, 9))
    for seg, (nome, cor) in SEG.items():
        g = corr[(corr.segmento == seg) & (corr.serie_voos == "nr_passageiros") &
                 (corr.serie_trends == "tr_curso_ingles") & (corr.transformacao == "nivel")]
        g = g.set_index("defasagem_semanas").reindex(ks)
        ax.plot(ks, g.pearson, color=cor, lw=2, marker="o", ms=4, label=nome)
        sig = g[g.significativo == True]
        ax.scatter(sig.index, sig.pearson, s=60, facecolor="none", edgecolor=cor, lw=1.5)
    ax.axvline(0, color=BASE, lw=1)
    ax.axhline(0, color=BASE, lw=1)
    ax.set_xticks(ks)
    ax.set_xlabel("defasagem em semanas (positivo = a busca vem depois do voo)")
    ax.set_ylabel('Pearson com "curso de inglês"')
    ax.set_title("Voos de férias em geral antecedem a busca; Europa não")
    ax.legend(loc="upper left", fontsize=8.5)
    ax.text(0.995, 0.02, "círculo vazado: p < 0,05 pelo tamanho efetivo", transform=ax.transAxes,
            ha="right", color=MUDO, fontsize=8)
    salvar(fig, "02_correlograma_por_destino.png")

    # 03: parciais
    p = parc[(parc.serie_trends == "tr_curso_ingles") & parc.defasagem_semanas.between(-2, 6)]
    fig, ax = plt.subplots(figsize=(9, 4))
    for i, (exp, ctl, cor, nome) in enumerate([
            ("anglofono", "nao_anglofono", AZUL, "anglófonos, descontados os não anglófonos"),
            ("nao_anglofono", "anglofono", LARANJA, "não anglófonos, descontados os anglófonos")]):
        g = p[(p.explicativa == exp) & (p.controle == ctl)].set_index("defasagem_semanas")
        x = g.index + (i - 0.5) * 0.38
        ax.bar(x, g.pearson_parcial, width=0.38, color=cor, label=nome, edgecolor=SUPERFICIE, lw=1.5)
        for xi, (_, r) in zip(x, g.iterrows()):
            if r.significativo:
                ax.text(xi, r.pearson_parcial + 0.02, "*", ha="center", color=TINTA2, fontsize=11)
    ax.axhline(0, color=BASE, lw=1)
    ax.set_xticks(range(-2, 7))
    ax.set_xlabel("defasagem em semanas")
    ax.set_ylabel("correlação parcial")
    ax.set_title('O que cada grupo de destino acrescenta sobre o outro na busca por "curso de inglês"')
    ax.legend(fontsize=8.5, loc="upper left")
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)
    ax.text(0.995, 0.02, "*: p < 0,05 pelo tamanho efetivo", transform=ax.transAxes, ha="right",
            color=MUDO, fontsize=8)
    salvar(fig, "03_parciais.png")

    # 04: volume x composicao
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4), sharey=True)
    y = tr.tr_curso_ingles.shift(-3)
    cores = tr.temporada.map({"férias escolares": LARANJA, "volta às aulas": VERDE_AGUA,
                              "período letivo": AZUL})
    r_vol = R["t3_participacao_anglofona"]["volume_internacional_defasagem3"]
    r_par = R["t3_participacao_anglofona"]["por_defasagem"][3]
    for ax, x, rot, rr in [(axes[0], larga.internacional / 1000, "passageiros internacionais na semana t (mil)", r_vol),
                           (axes[1], part.anglofono, "% dos passageiros internacionais indo para EUA, Canadá ou Reino Unido (semana t)", r_par)]:
        ok = y.notna()
        ax.scatter(x[ok], y[ok], c=cores[ok], s=38, edgecolor=SUPERFICIE, lw=1.2)
        ax.set_xlabel(rot, fontsize=9)
        ax.set_title(f"Pearson {rr['r']:+.2f} (p = {rr['p_efetivo']:.3f})", fontsize=10)
    axes[0].set_ylabel('busca "curso de inglês" na semana t+3')
    for temp, cor in [("férias escolares", LARANJA), ("volta às aulas", VERDE_AGUA), ("período letivo", AZUL)]:
        axes[1].scatter([], [], color=cor, s=38, label=temp)
    axes[1].legend(title="temporada da semana t", fontsize=8.5, title_fontsize=8.5, ncol=3,
                   loc="upper center", bbox_to_anchor=(-0.05, -0.16))
    fig.suptitle("Quanto se viaja importa; para onde se viaja, não", fontweight="bold", color=TINTA)
    salvar(fig, "04_volume_x_composicao.png")

    # 05: perfil por temporada
    perfil = pd.DataFrame(R["t5_perfil_temporada"])
    ordem = ["férias escolares", "volta às aulas", "período letivo"]
    segs = ["anglofono", "nao_anglofono_america_sul", "nao_anglofono_europa", "nao_anglofono_america_cn"]
    nomes = ["Anglófonos", "América do Sul", "Europa", "América Central\ne México"]
    fig, ax = plt.subplots(figsize=(9, 4))
    x = np.arange(len(segs))
    for i, (temp, cor) in enumerate(zip(ordem, [LARANJA, VERDE_AGUA, AZUL])):
        ax.bar(x + (i - 1) * 0.27, perfil.loc[temp, segs].values - 100, width=0.27, color=cor,
               label=temp, edgecolor=SUPERFICIE, lw=1.5)
    ax.axhline(0, color=BASE, lw=1)
    ax.set_xticks(x, nomes)
    ax.set_ylabel("% acima / abaixo da média do destino")
    ax.set_title("Passageiros por temporada escolar, por destino")
    ax.legend(fontsize=8.5)
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)
    salvar(fig, "05_perfil_temporada_destinos.png")


if __name__ == "__main__":
    main()
