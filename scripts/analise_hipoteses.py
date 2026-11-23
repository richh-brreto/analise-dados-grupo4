"""
Testes das hipoteses sobre voos para paises anglofonos x intencao de estudar
ingles, a partir das tabelas gold. Gera os graficos estaticos do relatorio e
um resumo numerico em JSON.

Entrada: data/gold/{cruzamento_semanal_br,cruzamento_semanal_uf,resumo_uf,correlacoes}
Saida:   graficos/cruzamento/*.png e graficos/cruzamento/resultados.json

Uso:
  pip install pandas numpy scipy statsmodels matplotlib
  python scripts/analise_hipoteses.py

Todos os testes usam so semanas completas. As series semanais tem forte
autocorrelacao, entao todo p-valor de correlacao em nivel usa o tamanho
efetivo da amostra (ver METODOLOGIA.md, secao 12).
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
from scipy import stats

warnings.filterwarnings("ignore")

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
GOLD = os.path.join(BASE_DIR, "data", "gold")
SAIDA = os.path.join(BASE_DIR, "graficos", "cruzamento")

# Paleta de referencia (validada para daltonismo nas tres primeiras posicoes)
AZUL, LARANJA, VERDE_AGUA = "#2a78d6", "#eb6834", "#1baf7a"
TINTA, TINTA2, MUDO, GRADE, BASE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SUPERFICIE = "#fcfcfb"
DIVERGENTE = ["#184f95", "#3987e5", "#9ec5f4", "#f0efec", "#f4a9a8", "#e34948", "#a02a2a"]

plt.rcParams.update({
    "figure.facecolor": SUPERFICIE, "axes.facecolor": SUPERFICIE, "savefig.facecolor": SUPERFICIE,
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": BASE,
    "axes.labelcolor": TINTA2, "xtick.color": MUDO, "ytick.color": MUDO,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRADE, "grid.linewidth": 0.6, "axes.titleweight": "bold",
    "axes.titlesize": 11, "axes.titlecolor": TINTA, "legend.frameon": False,
})


RAMPA = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281", "#0d366b"]


def rampa_anos(n):
    """Rampa ordinal de azul, do ano mais antigo (claro) ao mais recente (escuro)."""
    if n <= 1:
        return [RAMPA[-2]]
    return [RAMPA[round(i * (len(RAMPA) - 1) / (n - 1))] for i in range(n)]


def eixo_datas(ax, datas):
    """Marcas trimestrais ate 2 anos de dados; semestrais acima disso."""
    meses = [1, 4, 7, 10] if (datas.max() - datas.min()).days <= 760 else [1, 7]
    ax.xaxis.set_major_locator(matplotlib.dates.MonthLocator(bymonth=meses))
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%m/%y"))


def ler(nome):
    return pd.read_csv(os.path.join(GOLD, nome, f"{nome}_parte0001.csv"), sep=";")


def r_p_efetivo(x, y):
    """Pearson com p-valor pelo tamanho efetivo (Bretherton et al., 1999)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    r = np.corrcoef(x, y)[0, 1]
    r1x = np.corrcoef(x[:-1], x[1:])[0, 1]
    r1y = np.corrcoef(y[:-1], y[1:])[0, 1]
    n_ef = min(len(x), max(3.0, len(x) * (1 - r1x * r1y) / (1 + r1x * r1y)))
    t = r * np.sqrt((n_ef - 2) / max(1e-12, 1 - r ** 2))
    p = 2 * stats.t.sf(abs(t), n_ef - 2)
    return {"r": round(float(r), 3), "p_efetivo": round(float(p), 4), "n": int(len(x)),
            "n_efetivo": round(float(n_ef), 1)}


def defasar(df, col, k):
    """Valor da coluna k semanas depois (k > 0) de cada semana."""
    return df[col].shift(-k)


def correlograma(df, x, y, kmax=8):
    return {k: r_p_efetivo(df[x], defasar(df, y, k)) for k in range(-kmax, kmax + 1)}


def parcial(df, x, y, z, k=0):
    """Correlacao de x com y(t+k) controlando por z(t+k)."""
    d = pd.DataFrame({"x": df[x], "y": defasar(df, y, k), "z": defasar(df, z, k)}).dropna()
    rx = d.x - np.polyval(np.polyfit(d.z, d.x, 1), d.z)
    ry = d.y - np.polyval(np.polyfit(d.z, d.y, 1), d.z)
    return r_p_efetivo(rx.values, ry.values)


def salvar(fig, nome):
    os.makedirs(SAIDA, exist_ok=True)
    fig.savefig(os.path.join(SAIDA, nome), dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    br = ler("cruzamento_semanal_br")
    uf = ler("cruzamento_semanal_uf")
    resumo = ler("resumo_uf")
    br["semana_inicio"] = pd.to_datetime(br.semana_inicio)
    uf["semana_inicio"] = pd.to_datetime(uf.semana_inicio)
    c = br[br.semana_completa].reset_index(drop=True)
    R = {}

    # H1: sazonalidade comum e defasagem
    R["h1_correlograma_pax_curso"] = correlograma(c, "nr_passageiros", "tr_curso_ingles")
    R["h1_correlograma_pax_intencao"] = correlograma(c, "nr_passageiros", "tr_intencao_ingles")
    R["h1_correlograma_pax_curso_online"] = correlograma(c, "nr_passageiros", "tr_curso_online")
    R["h1_correlograma_pax_razao"] = correlograma(c, "nr_passageiros", "tr_razao_ingles_curso_online")
    R["h1_correlograma_pax_passagem"] = correlograma(c, "nr_passageiros", "tr_passagem_aerea")
    R["h1_termos_lag0"] = {t: r_p_efetivo(c.nr_passageiros, c[t]) for t in
                           ["tr_curso_ingles", "tr_aula_ingles", "tr_aprender_ingles",
                            "tr_ingles_online", "tr_professor_ingles", "tr_intencao_ingles"]}

    # H2: o calendario educacional generico explica a relacao?
    R["h2_parcial_controle_curso_online"] = {k: parcial(c, "nr_passageiros", "tr_curso_ingles",
                                                        "tr_curso_online", k) for k in (0, 2, 3, 4)}

    # H3: a relacao sobrevive sem dezembro e janeiro?
    sem_verao = c[~c.mes_referencia.isin([12, 1])].reset_index(drop=True)
    R["h3_sem_dez_jan"] = {k: r_p_efetivo(sem_verao.nr_passageiros, defasar(sem_verao, "tr_curso_ingles", k))
                           for k in (0, 2, 3, 4)}
    R["h3_sem_dez_jan_semanas"] = int(len(sem_verao))

    # H4: ano contra ano, mesma semana do ano, todos os pares de anos seguidos
    anos = sorted(c.ano_semana.unique())
    dpax, dcur, pares_anos = [], [], []
    for a0, a1 in zip(anos, anos[1:]):
        x0 = c[c.ano_semana == a0].set_index("num_semana")
        x1 = c[c.ano_semana == a1].set_index("num_semana")
        comuns = x0.index.intersection(x1.index)
        if len(comuns) < 4:
            continue
        dpax.append(np.log(x1.loc[comuns, "nr_passageiros"] / x0.loc[comuns, "nr_passageiros"]))
        dcur.append(np.log(x1.loc[comuns, "tr_curso_ingles"] / x0.loc[comuns, "tr_curso_ingles"]))
        pares_anos.append(f"{a1} x {a0} ({len(comuns)} semanas)")
    dpax, dcur = pd.concat(dpax), pd.concat(dcur)
    R["h4_ano_contra_ano"] = {
        **r_p_efetivo(dpax.values, dcur.values),
        "pares": pares_anos,
        "var_pax_media_pct": round(float(100 * (np.exp(dpax.mean()) - 1)), 2),
        "var_curso_media_pct": round(float(100 * (np.exp(dcur.mean()) - 1)), 2),
    }

    # H5: julho, o pico de ferias sem efeito de ano-novo (semanas pelo mes da quarta-feira)
    jul = {}
    for ano in anos:
        junho = c[(c.ano_semana == ano) & (c.mes_referencia == 6)]
        julho = c[(c.ano_semana == ano) & (c.mes_referencia == 7)]
        if len(junho) < 3 or len(julho) < 3:
            continue
        jul[int(ano)] = {col: round(100 * (julho[col].mean() / junho[col].mean() - 1), 1)
                         for col in ["nr_passageiros", "tr_curso_ingles", "tr_curso_online",
                                     "tr_razao_ingles_curso_online", "tr_aula_ingles"]}
    R["h5_julho_vs_junho_pct"] = jul

    # H6: perfil por temporada (indice = media da temporada / media geral x 100)
    cols6 = ["nr_passageiros", "tr_curso_ingles", "tr_aula_ingles", "tr_professor_ingles",
             "tr_aprender_ingles", "tr_ingles_online", "tr_curso_online", "tr_passagem_aerea"]
    perfil = (c.groupby("temporada")[cols6].mean() / c[cols6].mean() * 100).round(1)
    R["h6_perfil_temporada"] = perfil.to_dict()

    # H7: regional
    reg = {}
    for u in ["SP", "RJ", "MG"]:
        d = uf[(uf.sg_uf == u) & uf.semana_completa].sort_values("semana_inicio").reset_index(drop=True)
        reg[u] = {k: r_p_efetivo(d.nr_passageiros, defasar(d, "tr_curso_ingles_uf", k)) for k in (0, 2, 3)}
        dd = d[~d.mes_referencia.isin([12, 1])].reset_index(drop=True)
        reg[u]["sem_dez_jan_lag0"] = r_p_efetivo(dd.nr_passageiros, dd.tr_curso_ingles_uf)
    R["h7_regional"] = reg
    com_voo = resumo[resumo.nr_passageiros > 0]
    rho, p = stats.spearmanr(com_voo.nr_passageiros, com_voo.interesse_curso_ingles)
    R["h7_transversal_ufs_com_voo"] = {"spearman": round(float(rho), 3), "p": round(float(p), 4),
                                       "n_ufs": int(len(com_voo))}

    # H8: precedencia (Granger) nas variacoes semanais, so como indicio
    from statsmodels.tsa.stattools import grangercausalitytests
    g = pd.DataFrame({"pax": np.log(c.nr_passageiros).diff(),
                      "curso": np.log(c.tr_curso_ingles).diff()}).dropna()
    gr = {}
    for nome, cols in {"voos_antecedem_busca": ["curso", "pax"],
                       "busca_antecede_voos": ["pax", "curso"]}.items():
        try:
            res = grangercausalitytests(g[cols], maxlag=4, verbose=False)
        except TypeError:          # statsmodels >= 0.15 removeu o parametro verbose
            res = grangercausalitytests(g[cols], maxlag=4)
        gr[nome] = {int(lag): round(float(res[lag][0]["ssr_ftest"][1]), 4) for lag in res}
    R["h8_granger_p"] = gr

    os.makedirs(SAIDA, exist_ok=True)
    with open(os.path.join(SAIDA, "resultados.json"), "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=2, default=str)

    graficos(br, c, uf, resumo, R)
    imprimir(R)


def graficos(br, c, uf, resumo, R):
    # 01: series indexadas na mesma base (0 a 100), sem eixo duplo
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.plot(c.semana_inicio, c.pax_indice, color=AZUL, lw=2, label="Passageiros (índice, 100 = maior semana)")
    ax.plot(c.semana_inicio, c.tr_curso_ingles, color=LARANJA, lw=2, label='Busca "curso de inglês"')
    ax.plot(c.semana_inicio, c.tr_curso_online, color=VERDE_AGUA, lw=2, label='Busca "curso online" (controle)')
    for _, l in c[c.temporada == "férias escolares"].iterrows():
        ax.axvspan(l.semana_inicio, l.semana_inicio + pd.Timedelta(days=7), color="#f0efec", lw=0, zorder=0)
    ax.set_ylim(0, 105)
    ax.set_ylabel("índice (0 a 100)")
    ax.set_title("Passageiros para EUA, Canadá e Reino Unido x busca por curso de inglês, por semana")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=3, fontsize=9)
    ax.text(0.995, 0.98, "faixas cinza: meses de férias escolares", transform=ax.transAxes,
            ha="right", va="top", color=MUDO, fontsize=8)
    salvar(fig, "01_series_semanais.png")

    # 02: correlograma cruzado
    fig, ax = plt.subplots(figsize=(9, 4))
    ks = list(range(-8, 9))
    for chave, cor, nome in [("h1_correlograma_pax_curso", LARANJA, '"curso de inglês"'),
                             ("h1_correlograma_pax_curso_online", VERDE_AGUA, '"curso online" (controle)'),
                             ("h1_correlograma_pax_passagem", AZUL, '"passagem aérea"')]:
        rs = [R[chave][k]["r"] for k in ks]
        ax.plot(ks, rs, color=cor, lw=2, marker="o", ms=4, label=nome)
        sig = [k for k in ks if R[chave][k]["p_efetivo"] < 0.05]
        ax.scatter(sig, [R[chave][k]["r"] for k in sig], s=60, facecolor="none", edgecolor=cor, lw=1.5)
    ax.axvline(0, color=BASE, lw=1)
    ax.axhline(0, color=BASE, lw=1)
    ax.set_xticks(ks)
    ax.set_xlabel("defasagem em semanas (positivo = a busca vem depois do voo)")
    ax.set_ylabel("Pearson com passageiros")
    ax.set_title("Correlação entre passageiros e busca, por defasagem")
    ax.legend(loc="upper left", fontsize=9)
    ax.text(0.995, 0.02, "círculo vazado: p < 0,05 pelo tamanho efetivo", transform=ax.transAxes,
            ha="right", color=MUDO, fontsize=8)
    salvar(fig, "02_correlograma_cruzado.png")

    # 03: dispersao, lag +3, por temporada
    fig, ax = plt.subplots(figsize=(7, 4.6))
    d = c.assign(busca3=defasar(c, "tr_curso_ingles", 3)).dropna(subset=["busca3"])
    for temp, cor in [("férias escolares", LARANJA), ("volta às aulas", VERDE_AGUA), ("período letivo", AZUL)]:
        s = d[d.temporada == temp]
        ax.scatter(s.nr_passageiros / 1000, s.busca3, s=40, color=cor, edgecolor=SUPERFICIE, lw=1.5, label=temp)
    ax.set_xlabel("passageiros na semana t (mil)")
    ax.set_ylabel('busca "curso de inglês" na semana t+3')
    ax.set_title("Semanas de muito voo são seguidas de mais busca")
    ax.legend(title="temporada da semana t", fontsize=9, title_fontsize=9)
    salvar(fig, "03_dispersao_defasagem3.png")

    # 04: mapa de calor das correlacoes no nivel, defasagem 0
    corr = ler("correlacoes")
    m = corr[(corr.recorte == "BR") & (corr.transformacao == "nivel") & (corr.defasagem_semanas == 0)]
    tab = m.pivot(index="serie_trends", columns="serie_voos", values="pearson")
    tab = tab.loc[["tr_intencao_ingles", "tr_curso_ingles", "tr_aula_ingles", "tr_aprender_ingles",
                   "tr_ingles_online", "tr_professor_ingles", "tr_razao_ingles_curso_online",
                   "tr_intercambio", "tr_visto_americano", "tr_passagem_aerea", "tr_curso_online"],
                  ["nr_passageiros", "qtd_voos", "pax_por_voo", "pax_eua", "pax_canada", "pax_reino_unido"]]
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("div", DIVERGENTE)
    fig, ax = plt.subplots(figsize=(8, 5.6))
    im = ax.imshow(tab.values, cmap=cmap, vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(tab.shape[1]), ["passageiros", "voos", "passageiros/voo", "pax EUA",
                                        "pax Canadá", "pax Reino Unido"], rotation=30, ha="right")
    ax.set_yticks(range(tab.shape[0]), ["intenção (5 termos)", "curso de inglês", "aula de inglês",
                                        "aprender inglês", "inglês online", "professor de inglês",
                                        "inglês ÷ curso online", "intercâmbio", "visto americano",
                                        "passagem aérea", "curso online"])
    for i in range(tab.shape[0]):
        for j in range(tab.shape[1]):
            v = tab.values[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8,
                    color="#ffffff" if abs(v) > 0.55 else TINTA)
    ax.grid(False)
    fig.colorbar(im, ax=ax, shrink=0.8, label="Pearson")
    ax.set_title("Correlações na mesma semana (Brasil, semanas completas)")
    salvar(fig, "04_mapa_correlacoes.png")

    # 05: regional, pequenos multiplos
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6), sharey=True)
    for ax, u in zip(axes, ["SP", "RJ", "MG"]):
        d = uf[(uf.sg_uf == u) & uf.semana_completa].sort_values("semana_inicio")
        pax = 100 * d.nr_passageiros / d.nr_passageiros.max()
        ax.plot(d.semana_inicio, pax, color=AZUL, lw=1.8, label="passageiros (índice)")
        ax.plot(d.semana_inicio, 100 * d.tr_curso_ingles_uf / d.tr_curso_ingles_uf.max(), color=LARANJA,
                lw=1.8, label='busca "curso de inglês" (índice)')
        r = R["h7_regional"][u][0]["r"]
        ax.set_title(f"{u}  (Pearson na mesma semana: {r:.2f})")
        eixo_datas(ax, d.semana_inicio)
        ax.set_ylim(0, 105)
    axes[0].set_ylabel("índice (100 = maior semana da UF)")
    axes[0].legend(loc="lower left", fontsize=8)
    fig.suptitle("Voos com embarque na UF x busca na UF", fontweight="bold", color=TINTA)
    salvar(fig, "05_regional_sp_rj_mg.png")

    # 06: transversal por UF
    fig, ax = plt.subplots(figsize=(8, 4.6))
    r = resumo.sort_values("interesse_curso_ingles", ascending=True)
    cores = [AZUL if p > 0 else GRADE for p in r.nr_passageiros]
    ax.set_axisbelow(True)
    ax.grid(axis="y", visible=False)
    ax.barh(r.sg_uf, r.interesse_curso_ingles, color=cores, height=0.7)
    for i, (_, l) in enumerate(r.iterrows()):
        if l.nr_passageiros > 0:
            ax.text(l.interesse_curso_ingles + 1, i, f"{l.pct_passageiros:.1f}% dos passageiros",
                    va="center", fontsize=7.5, color=TINTA2)
    ax.set_xlim(0, 125)
    ax.set_xlabel('interesse por "curso de inglês" (100 = UF com mais busca relativa)')
    ax.set_title("Interesse por UF e participação nos embarques para os 3 destinos")
    ax.text(0.995, 0.02, "azul: UF com voo comercial direto para os destinos", transform=ax.transAxes,
            ha="right", color=MUDO, fontsize=8)
    ax.tick_params(axis="y", labelsize=8)
    salvar(fig, "06_interesse_por_uf.png")

    # 07: sobreposicao ano a ano
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8))
    for ax, col, titulo in [(axes[0], "nr_passageiros", "Passageiros por semana do ano"),
                            (axes[1], "tr_curso_ingles", 'Busca "curso de inglês" por semana do ano')]:
        anos = sorted(c.ano_semana.unique())
        for ano, cor in zip(anos, rampa_anos(len(anos))):
            d = c[c.ano_semana == ano]
            y = d[col] / 1000 if col == "nr_passageiros" else d[col]
            ax.plot(d.num_semana, y, color=cor, lw=2, label=str(ano))
        ax.set_title(titulo)
        ax.set_xlabel("semana do ano")
        ax.legend(fontsize=9)
    axes[0].set_ylabel("mil passageiros")
    salvar(fig, "07_ano_a_ano.png")

    # 08: perfil por temporada
    perfil = pd.DataFrame(R["h6_perfil_temporada"])
    ordem = ["férias escolares", "volta às aulas", "período letivo"]
    cols = ["nr_passageiros", "tr_curso_ingles", "tr_aprender_ingles", "tr_ingles_online",
            "tr_aula_ingles", "tr_professor_ingles", "tr_curso_online"]
    nomes = ["passageiros", "curso de inglês", "aprender inglês", "inglês online",
             "aula de inglês", "professor de inglês", "curso online (controle)"]
    fig, ax = plt.subplots(figsize=(10, 4))
    x = np.arange(len(cols))
    for i, (temp, cor) in enumerate(zip(ordem, [LARANJA, VERDE_AGUA, AZUL])):
        ax.bar(x + (i - 1) * 0.27, perfil.loc[temp, cols].values - 100, width=0.27, color=cor, label=temp,
               edgecolor=SUPERFICIE, linewidth=1.5)
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)
    ax.axhline(0, color=BASE, lw=1)
    ax.set_xticks(x, nomes, rotation=15)
    ax.set_ylabel("% acima / abaixo da média do período")
    ax.set_title("Cada série por temporada escolar")
    ax.legend(fontsize=9)
    salvar(fig, "08_perfil_temporada.png")


def imprimir(R):
    def lin(d):
        return f"r={d['r']:+.2f} p={d['p_efetivo']:.3f} n={d['n']} n_ef={d['n_efetivo']}"
    print("H1 pax x curso de ingles:", {k: R["h1_correlograma_pax_curso"][k]["r"] for k in range(-2, 6)})
    for t, d in R["h1_termos_lag0"].items():
        print(f"  {t}: {lin(d)}")
    print("H2 parcial (controle curso online):", {k: lin(d) for k, d in R["h2_parcial_controle_curso_online"].items()})
    print("H3 sem dez/jan:", {k: lin(d) for k, d in R["h3_sem_dez_jan"].items()})
    print("H4 ano contra ano:", R["h4_ano_contra_ano"])
    print("H5 julho vs junho (%):", R["h5_julho_vs_junho_pct"])
    print("H6 perfil:", json.dumps(R["h6_perfil_temporada"], ensure_ascii=False))
    print("H7 regional:", {u: {k: lin(d) for k, d in v.items()} for u, v in R["h7_regional"].items()})
    print("H7 transversal:", R["h7_transversal_ufs_com_voo"])
    print("H8 Granger p:", R["h8_granger_p"])


if __name__ == "__main__":
    main()
