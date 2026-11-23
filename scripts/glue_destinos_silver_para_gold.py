"""
Job do AWS Glue (Spark) do grupo de comparacao: cruza os voos semanais por
grupo de destino (silver voos_semanal_destinos) com as series do Google Trends
(silver google_trends_semanal) e grava no gold as tabelas que separam o efeito
das ferias do efeito do destino de lingua inglesa. Fica separado de
glue_silver_para_gold.py para nao misturar com o recorte do projeto.

Saida (gold), UTF-8, separador ';':
  comparacao_destinos_semanal   semana x segmento de destino: voos, passageiros,
                                indice, participacao no total internacional e as
                                series do Trends da semana
  correlacoes_destinos          Pearson e Spearman entre cada segmento e cada
                                serie do Trends, defasagem de -8 a +8 semanas
  parciais_destinos             correlacao parcial: anglofono controlando por
                                nao anglofono e vice-versa

Segmentos (METODOLOGIA.md, secao 15):
  anglofono                     RECORTE: EUA, Canada e Reino Unido
  nao_anglofono                 todos os destinos nao anglofonos
  nao_anglofono_america_sul     Argentina, Chile, Uruguai, Paraguai...
  nao_anglofono_europa          Portugal, Espanha, Franca, Italia...
  nao_anglofono_america_cn      America Central e Mexico (Panama, Caribe...)
  nao_anglofono_outros          Africa, Asia e Oceania
  outro_anglofono               Africa do Sul e anglofonos menores
  internacional                 todos os destinos

Parametros do job no Glue: --SILVER_BUCKET e --GOLD_BUCKET (so o nome).

Execucao local:
  python glue_destinos_silver_para_gold.py --local data/silver data/gold
"""
import csv
import datetime as dt
import io
import math
import os
import sys
from collections import defaultdict

from pyspark.sql import SparkSession

DEFASAGEM_MAX = 8
MIN_PARES = 20

SEGMENTOS = [
    ("anglofono", "Anglófono (EUA, Canadá, Reino Unido)",
     lambda g, c: g == "RECORTE"),
    ("nao_anglofono", "Não anglófono (todos)",
     lambda g, c: g == "NÃO ANGLÓFONO"),
    ("nao_anglofono_america_sul", "Não anglófono: América do Sul",
     lambda g, c: g == "NÃO ANGLÓFONO" and c == "AMÉRICA DO SUL"),
    ("nao_anglofono_europa", "Não anglófono: Europa",
     lambda g, c: g == "NÃO ANGLÓFONO" and c == "EUROPA"),
    ("nao_anglofono_america_cn", "Não anglófono: América Central e México",
     lambda g, c: g == "NÃO ANGLÓFONO" and c in ("AMÉRICA CENTRAL", "AMÉRICA DO NORTE")),
    ("nao_anglofono_outros", "Não anglófono: África, Ásia e Oceania",
     lambda g, c: g == "NÃO ANGLÓFONO" and c in ("ÁFRICA", "ÁSIA", "OCEANIA")),
    ("outro_anglofono", "Outro anglófono (África do Sul e menores)",
     lambda g, c: g == "OUTRO ANGLÓFONO"),
    ("internacional", "Internacional (todos os destinos)",
     lambda g, c: True),
]
SEGMENTOS_CORR = [s for s, _, _ in SEGMENTOS if s != "outro_anglofono"]

TRENDS = {
    ("intencao_ingles", "curso de inglês"): "tr_curso_ingles",
    ("intencao_ingles", "aula de inglês"): "tr_aula_ingles",
    ("intencao_ingles", "aprender inglês"): "tr_aprender_ingles",
    ("intencao_ingles", "inglês online"): "tr_ingles_online",
    ("intencao_ingles", "professor de inglês"): "tr_professor_ingles",
    ("contexto_viagem", "curso online"): "tr_curso_online",
    ("contexto_viagem", "curso de inglês"): "_curso_ingles_ctx",
}
TERMOS_INTENCAO = ["tr_curso_ingles", "tr_aula_ingles", "tr_aprender_ingles",
                   "tr_ingles_online", "tr_professor_ingles"]
SERIES_TRENDS = ["tr_curso_ingles", "tr_intencao_ingles", "tr_aula_ingles", "tr_curso_online",
                 "tr_razao_ingles_curso_online"]

CALENDARIO = ["semana_inicio", "semana_fim", "ano_semana", "num_semana", "mes_referencia",
              "estacao", "temporada", "dias_cobertos", "semana_completa"]
COLUNAS_SEMANAL = CALENDARIO + ["segmento", "segmento_nome", "qtd_voos", "nr_passageiros",
                                "pax_indice", "participacao_pax"] + SERIES_TRENDS
COLUNAS_CORR = ["segmento", "serie_voos", "serie_trends", "transformacao", "defasagem_semanas",
                "pearson", "spearman", "n", "n_efetivo", "r_critico_5pct", "significativo"]
COLUNAS_PARCIAL = ["serie_trends", "explicativa", "controle", "defasagem_semanas",
                   "pearson_parcial", "pearson_simples", "n", "n_efetivo", "r_critico_5pct",
                   "significativo"]


def ler(spark, caminho):
    linhas = (spark.read.option("header", True).option("sep", ";").option("encoding", "UTF-8")
              .option("recursiveFileLookup", "true").csv(caminho).collect())
    return [r.asDict() for r in linhas]


def num(v):
    return None if v in (None, "") else float(v)


# ------------------------------------------------------------- estatistica
def pearson(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return None if sxx == 0 or syy == 0 else sxy / math.sqrt(sxx * syy)


def postos(v):
    ordem = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and v[ordem[j + 1]] == v[ordem[i]]:
            j += 1
        for k in range(i, j + 1):
            r[ordem[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def autocorr1(v):
    return (pearson(v[:-1], v[1:]) or 0.0) if len(v) > 3 else 0.0


def n_efetivo(a, b):
    r1a, r1b = autocorr1(a), autocorr1(b)
    return min(len(a), max(3.0, len(a) * (1 - r1a * r1b) / (1 + r1a * r1b)))


def r_critico(n_ef):
    return min(1.0, 1.96 / math.sqrt(max(n_ef - 2, 1)))


def residuo(y, z):
    """Residuo da regressao linear de y em z."""
    my, mz = sum(y) / len(y), sum(z) / len(z)
    szz = sum((b - mz) ** 2 for b in z)
    beta = sum((a - my) * (b - mz) for a, b in zip(y, z)) / szz if szz else 0.0
    return [a - my - beta * (b - mz) for a, b in zip(y, z)]


def alinhar(semanas, k, *series):
    """Tuplas (s0[t], ..., y[t+k]); a ultima serie e a defasada."""
    out = []
    for i, s in enumerate(semanas):
        j = i + k
        if 0 <= j < len(semanas):
            vals = [x.get(s) for x in series[:-1]] + [series[-1].get(semanas[j])]
            if all(v is not None for v in vals):
                out.append(vals)
    return out


def diferenca(serie, semanas):
    return {b: serie[b] - serie[a] for a, b in zip(semanas, semanas[1:])
            if serie.get(a) is not None and serie.get(b) is not None}


def correlacoes(segmento, series_x, series_y, semanas):
    linhas = []
    for transf in ("nivel", "variacao"):
        sem = semanas if transf == "nivel" else semanas[1:]
        for nx, x in series_x.items():
            x = x if transf == "nivel" else diferenca(x, semanas)
            for ny, y in series_y.items():
                y = y if transf == "nivel" else diferenca(y, semanas)
                for k in range(-DEFASAGEM_MAX, DEFASAGEM_MAX + 1):
                    p = alinhar(sem, k, x, y)
                    if len(p) < MIN_PARES:
                        continue
                    a, b = [u for u, _ in p], [v for _, v in p]
                    r = pearson(a, b)
                    if r is None:
                        continue
                    ne = n_efetivo(a, b)
                    rc = r_critico(ne)
                    linhas.append([segmento, nx, ny, transf, k, round(r, 4),
                                   round(pearson(postos(a), postos(b)), 4), len(p), round(ne, 1),
                                   round(rc, 4), "true" if abs(r) > rc else "false"])
    return linhas


def parciais(serie_trends, y, explicativa, x, controle, z, semanas):
    linhas = []
    for k in range(-DEFASAGEM_MAX, DEFASAGEM_MAX + 1):
        p = alinhar(semanas, k, x, z, y)
        if len(p) < MIN_PARES:
            continue
        xs, zs, ys = zip(*p)
        rx, ry = residuo(list(xs), list(zs)), residuo(list(ys), list(zs))
        r = pearson(rx, ry)
        if r is None:
            continue
        ne = n_efetivo(rx, ry)
        rc = r_critico(ne)
        linhas.append([serie_trends, explicativa, controle, k, round(r, 4),
                       round(pearson(list(xs), list(ys)), 4), len(p), round(ne, 1), round(rc, 4),
                       "true" if abs(r) > rc else "false"])
    return linhas


# ------------------------------------------------------------------ tabelas
def montar(voos, trends):
    cal, pax, qtd = {}, defaultdict(float), defaultdict(int)
    for r in voos:
        s = r["semana_inicio"]
        cal[s] = {c: r[c] for c in CALENDARIO}
        for seg, _, regra in SEGMENTOS:
            if regra(r["grupo_destino"], r["nm_continente_destino"]):
                pax[(s, seg)] += int(r["nr_passageiros"])
                qtd[(s, seg)] += int(r["qtd_voos"])

    tr = defaultdict(dict)
    for r in trends:
        col = TRENDS.get((r["grupo"], r["termo"]))
        if col and r["geo"] == "BR":
            tr[r["semana_inicio"]][col] = num(r["valor"])
    soma = {s: sum(d[t] for t in TERMOS_INTENCAO) for s, d in tr.items()
            if all(d.get(t) is not None for t in TERMOS_INTENCAO)}
    max_soma = max(soma.values())
    for s, d in tr.items():
        d["tr_intencao_ingles"] = round(100 * soma[s] / max_soma, 2) if s in soma else None
        ctx, online = d.get("_curso_ingles_ctx"), d.get("tr_curso_online")
        d["tr_razao_ingles_curso_online"] = round(100 * ctx / online, 2) if ctx and online else None

    semanas = sorted(set(cal) & set(tr))
    completas = [s for s in semanas if cal[s]["semana_completa"] == "true"]
    maximo = {seg: max(pax[(s, seg)] for s in completas) for seg, _, _ in SEGMENTOS}

    tabela = []
    for s in semanas:
        for seg, nome, _ in SEGMENTOS:
            p = pax[(s, seg)]
            tabela.append({**cal[s], "segmento": seg, "segmento_nome": nome,
                           "qtd_voos": qtd[(s, seg)], "nr_passageiros": int(p),
                           "pax_indice": round(100 * p / maximo[seg], 2) if maximo[seg] else None,
                           "participacao_pax": round(100 * p / pax[(s, "internacional")], 3),
                           **{t: tr[s].get(t) for t in SERIES_TRENDS}})

    series_y = {t: {s: tr[s].get(t) for s in completas} for t in SERIES_TRENDS}
    corr = []
    for seg in SEGMENTOS_CORR:
        sx = {"nr_passageiros": {s: pax[(s, seg)] for s in completas}}
        if seg != "internacional":
            sx["participacao_pax"] = {s: 100 * pax[(s, seg)] / pax[(s, "internacional")] for s in completas}
        corr += correlacoes(seg, sx, series_y, completas)

    ang = {s: pax[(s, "anglofono")] for s in completas}
    nao = {s: pax[(s, "nao_anglofono")] for s in completas}
    parc = []
    for t, y in series_y.items():
        parc += parciais(t, y, "anglofono", ang, "nao_anglofono", nao, completas)
        parc += parciais(t, y, "nao_anglofono", nao, "anglofono", ang, completas)
    return tabela, corr, parc


def csv_bytes(colunas, linhas):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(colunas)
    for l in linhas:
        vals = [l[c] for c in colunas] if isinstance(l, dict) else l
        w.writerow(["" if v is None else v for v in vals])
    return buf.getvalue().encode("utf-8")


def gravar(conteudo, raiz, nome):
    chave = f"{nome}/{nome}_parte0001.csv"
    if raiz.startswith("s3://"):
        import boto3
        bucket = raiz[len("s3://"):].split("/")[0]
        boto3.client("s3").put_object(Bucket=bucket, Key=chave, Body=conteudo,
                                      ContentType="text/csv; charset=utf-8")
    else:
        caminho = os.path.join(raiz, chave)
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "wb") as f:
            f.write(conteudo)
    print(f"Gravado: {raiz.rstrip('/')}/{chave}")


def executar(spark, silver, gold):
    silver = silver.rstrip("/")
    tabela, corr, parc = montar(ler(spark, f"{silver}/voos_semanal_destinos"),
                                ler(spark, f"{silver}/google_trends_semanal"))
    print(f"Semanal: {len(tabela)} linhas; correlacoes: {len(corr)}; parciais: {len(parc)}")
    gravar(csv_bytes(COLUNAS_SEMANAL, tabela), gold, "comparacao_destinos_semanal")
    gravar(csv_bytes(COLUNAS_CORR, corr), gold, "correlacoes_destinos")
    gravar(csv_bytes(COLUNAS_PARCIAL, parc), gold, "parciais_destinos")


def main():
    if "--local" in sys.argv:
        i = sys.argv.index("--local")
        silver, gold = sys.argv[i + 1], sys.argv[i + 2]
        spark = SparkSession.builder.appName("comparacao_destinos").getOrCreate()
        executar(spark, silver, gold)
        spark.stop()
        return

    from awsglue.context import GlueContext
    from awsglue.job import Job
    from awsglue.utils import getResolvedOptions
    from pyspark.context import SparkContext

    args = getResolvedOptions(sys.argv, ["JOB_NAME", "SILVER_BUCKET", "GOLD_BUCKET"])
    glue = GlueContext(SparkContext.getOrCreate())
    job = Job(glue)
    job.init(args["JOB_NAME"], args)
    executar(glue.spark_session, f"s3://{args['SILVER_BUCKET']}", f"s3://{args['GOLD_BUCKET']}")
    job.commit()


if __name__ == "__main__":
    main()
