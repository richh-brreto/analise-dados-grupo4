"""
Job do AWS Glue (Spark) que cruza, no bucket silver, os voos semanais da ANAC
com as series semanais do Google Trends e grava no bucket gold as tabelas
prontas para o Athena e o Grafana. A chave comum e semana_inicio (domingo).

Entrada (silver), UTF-8, separador ';':
  voos_semanal/*.csv             glue_bronze_para_silver.py (ou voos_semanal.py)
  voos_semanal_uf/*.csv          glue_bronze_para_silver.py (ou voos_semanal.py)
  google_trends_semanal/*.csv    glue_trends_bronze_para_silver.py
  google_trends_mapa_uf/*.csv    glue_trends_bronze_para_silver.py

Saida (gold), UTF-8, separador ';', uma pasta por tabela:
  cruzamento_semanal_br   uma linha por semana: voos (total e por pais) e
                          todas as series do Trends do Brasil
  cruzamento_semanal_uf   uma linha por semana x UF: voos com embarque na UF e
                          interesse por "curso de ingles" na UF
  resumo_uf               uma linha por UF (27): voos no periodo, interesse
                          por UF e correlacao semanal quando ha as duas series
  correlacoes             Pearson e Spearman entre cada serie de voos e cada
                          serie do Trends, por recorte, transformacao e
                          defasagem de -8 a +8 semanas

So semanas completas (7 dias cobertos pela base da ANAC) entram nas
correlacoes. Ver METODOLOGIA.md, secoes 11 e 12.

Parametros do job no Glue: --SILVER_BUCKET e --GOLD_BUCKET (so o nome).

Execucao local, para teste, com pastas no mesmo formato dos buckets:
  python glue_silver_para_gold.py --local data/silver data/gold
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

PAISES = {"ESTADOS UNIDOS DA AMÉRICA": "eua", "CANADÁ": "canada", "REINO UNIDO": "reino_unido"}

# (grupo, termo) do Trends -> coluna na tabela gold do Brasil
SERIES_TRENDS_BR = {
    ("intencao_ingles", "curso de inglês"): "tr_curso_ingles",
    ("intencao_ingles", "aula de inglês"): "tr_aula_ingles",
    ("intencao_ingles", "aprender inglês"): "tr_aprender_ingles",
    ("intencao_ingles", "inglês online"): "tr_ingles_online",
    ("intencao_ingles", "professor de inglês"): "tr_professor_ingles",
    ("contexto_viagem", "intercâmbio"): "tr_intercambio",
    ("contexto_viagem", "visto americano"): "tr_visto_americano",
    ("contexto_viagem", "passagem aérea"): "tr_passagem_aerea",
    ("contexto_viagem", "curso online"): "tr_curso_online",
}
TERMOS_INTENCAO = ["tr_curso_ingles", "tr_aula_ingles", "tr_aprender_ingles",
                   "tr_ingles_online", "tr_professor_ingles"]
GRUPO_UF, TERMO_UF = "uf_curso_ingles", "curso de inglês"

UFS = {
    "AC": ("Acre", "Norte"), "AL": ("Alagoas", "Nordeste"), "AM": ("Amazonas", "Norte"),
    "AP": ("Amapá", "Norte"), "BA": ("Bahia", "Nordeste"), "CE": ("Ceará", "Nordeste"),
    "DF": ("Distrito Federal", "Centro-Oeste"), "ES": ("Espírito Santo", "Sudeste"),
    "GO": ("Goiás", "Centro-Oeste"), "MA": ("Maranhão", "Nordeste"),
    "MG": ("Minas Gerais", "Sudeste"), "MS": ("Mato Grosso do Sul", "Centro-Oeste"),
    "MT": ("Mato Grosso", "Centro-Oeste"), "PA": ("Pará", "Norte"), "PB": ("Paraíba", "Nordeste"),
    "PE": ("Pernambuco", "Nordeste"), "PI": ("Piauí", "Nordeste"), "PR": ("Paraná", "Sul"),
    "RJ": ("Rio de Janeiro", "Sudeste"), "RN": ("Rio Grande do Norte", "Nordeste"),
    "RO": ("Rondônia", "Norte"), "RR": ("Roraima", "Norte"), "RS": ("Rio Grande do Sul", "Sul"),
    "SC": ("Santa Catarina", "Sul"), "SE": ("Sergipe", "Nordeste"), "SP": ("São Paulo", "Sudeste"),
    "TO": ("Tocantins", "Norte"),
}

# Eventos de calendario que deslocam a demanda (anotacoes do Grafana). Carnaval e
# Semana Santa saem da data da Pascoa; os demais sao fixos. Calculados para todos
# os anos presentes nos dados.
COPAS = [("2022-11-20", "Copa do Mundo (Catar)"), ("2022-12-18", "Final da Copa do Mundo"),
         ("2026-06-11", "Copa do Mundo (EUA, Canadá, México)"), ("2026-07-19", "Final da Copa do Mundo")]


def pascoa(ano):
    """Domingo de Pascoa (algoritmo de Meeus/Jones/Butcher, calendario gregoriano)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return dt.date(ano, mes, dia)


def eventos(anos):
    lista = []
    for ano in sorted(anos):
        p = pascoa(ano)
        lista += [(f"{ano}-01-01", "Ano-novo"),
                  ((p - dt.timedelta(days=47)).isoformat(), "Carnaval"),
                  ((p - dt.timedelta(days=2)).isoformat(), "Semana Santa"),
                  (f"{ano}-12-25", "Natal")]
    return lista + [(d, n) for d, n in COPAS if int(d[:4]) in anos]


COLUNAS_BR = (
    ["semana_inicio", "semana_fim", "ano_semana", "num_semana", "mes_referencia", "estacao",
     "temporada", "dias_cobertos", "semana_completa", "evento",
     "qtd_voos", "nr_passageiros", "pax_por_voo", "pax_indice",
     "voos_eua", "voos_canada", "voos_reino_unido", "pax_eua", "pax_canada", "pax_reino_unido",
     "tr_intencao_ingles"] + TERMOS_INTENCAO +
    ["tr_intercambio", "tr_visto_americano", "tr_passagem_aerea", "tr_curso_online",
     "tr_razao_ingles_curso_online"]
)
COLUNAS_UF = ["semana_inicio", "semana_fim", "ano_semana", "num_semana", "mes_referencia",
              "temporada", "semana_completa", "sg_uf", "nome_uf", "regiao",
              "qtd_voos", "nr_passageiros", "tr_curso_ingles_uf", "tem_dado_trends", "cruzamento"]
COLUNAS_RESUMO = ["sg_uf", "nome_uf", "regiao", "qtd_voos", "nr_passageiros", "pct_passageiros",
                  "interesse_curso_ingles", "serie_semanal_trends", "semanas_com_dado_trends",
                  "pearson_semanal", "pares_semanal"]
COLUNAS_CORR = ["recorte", "serie_voos", "serie_trends", "transformacao", "defasagem_semanas",
                "pearson", "spearman", "n", "n_efetivo", "r_critico_5pct", "significativo"]

SERIES_VOOS_BR = ["nr_passageiros", "qtd_voos", "pax_por_voo", "pax_eua", "pax_canada",
                  "pax_reino_unido"]
SERIES_TRENDS_CORR = ["tr_intencao_ingles"] + TERMOS_INTENCAO + [
    "tr_intercambio", "tr_visto_americano", "tr_passagem_aerea", "tr_curso_online",
    "tr_razao_ingles_curso_online"]


# ----------------------------------------------------------------- leitura
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
    return pearson(v[:-1], v[1:]) if len(v) > 3 else None


def pares(serie_x, serie_y, semanas, k):
    """Pares (x[t], y[t+k]) nas semanas t em que os dois lados existem."""
    idx = {s: i for i, s in enumerate(semanas)}
    out = []
    for s in semanas:
        j = idx[s] + k
        if 0 <= j < len(semanas):
            a, b = serie_x.get(s), serie_y.get(semanas[j])
            if a is not None and b is not None:
                out.append((a, b))
    return out


def diferenca(serie, semanas):
    out = {}
    for ant, atual in zip(semanas, semanas[1:]):
        a, b = serie.get(ant), serie.get(atual)
        if a is not None and b is not None and (dt.date.fromisoformat(atual)
                                                - dt.date.fromisoformat(ant)).days == 7:
            out[atual] = b - a
    return out


def correlacoes(recorte, series_x, series_y, semanas):
    """Pearson e Spearman com defasagem k: voos na semana t, busca na semana t+k.

    k > 0: a busca vem depois do voo. k < 0: a busca vem antes.
    n_efetivo desconta a autocorrelacao de lag 1 das duas series
    (aproximacao de Bretherton et al., 1999), porque semanas vizinhas nao sao
    observacoes independentes; r_critico_5pct = 1,96 / raiz(n_efetivo - 2).
    """
    linhas = []
    for transf in ("nivel", "variacao"):
        sx = {n: s if transf == "nivel" else diferenca(s, semanas) for n, s in series_x.items()}
        sy = {n: s if transf == "nivel" else diferenca(s, semanas) for n, s in series_y.items()}
        sem = semanas if transf == "nivel" else semanas[1:]
        for nx, x in sx.items():
            for ny, y in sy.items():
                for k in range(-DEFASAGEM_MAX, DEFASAGEM_MAX + 1):
                    p = pares(x, y, sem, k)
                    if len(p) < MIN_PARES:
                        continue
                    a, b = [u for u, _ in p], [v for _, v in p]
                    r = pearson(a, b)
                    if r is None:
                        continue
                    rs = pearson(postos(a), postos(b))
                    r1a, r1b = autocorr1(a) or 0.0, autocorr1(b) or 0.0
                    n_ef = min(len(p), max(3.0, len(p) * (1 - r1a * r1b) / (1 + r1a * r1b)))
                    r_crit = min(1.0, 1.96 / math.sqrt(max(n_ef - 2, 1)))
                    linhas.append([recorte, nx, ny, transf, k, round(r, 4), round(rs, 4),
                                   len(p), round(n_ef, 1), round(r_crit, 4),
                                   "true" if abs(r) > r_crit else "false"])
    return linhas


# ------------------------------------------------------------------- tabelas
def semana_de(data):
    d = dt.date.fromisoformat(data)
    return (d - dt.timedelta(days=(d.weekday() + 1) % 7)).isoformat()


def montar(voos_br, voos, trends, mapa):
    anos = {int(r["semana_inicio"][:4]) for r in voos_br} | {int(r["semana_fim"][:4]) for r in voos_br}
    por_semana = defaultdict(list)
    for data, nome in sorted(eventos(anos)):
        por_semana[semana_de(data)].append(nome)

    # Brasil inteiro: voos_semanal (sem dupla contagem de voo com dois embarques).
    # Os atributos de calendario vem dele e sao iguais em todas as linhas da semana.
    cal = {}
    br = defaultdict(lambda: defaultdict(float))
    for r in voos_br:
        s, pais = r["semana_inicio"], PAISES[r["nm_pais_destino"]]
        cal[s] = {c: r[c] for c in ["semana_inicio", "semana_fim", "ano_semana", "num_semana",
                                    "mes_referencia", "estacao", "temporada", "dias_cobertos",
                                    "semana_completa"]}
        q, p = int(r["qtd_voos"]), int(r["nr_passageiros"])
        br[s]["qtd_voos"] += q
        br[s]["nr_passageiros"] += p
        br[s][f"voos_{pais}"] += q
        br[s][f"pax_{pais}"] += p

    # Por UF: voos com embarque na UF e passageiros embarcados nela
    uf_voos = defaultdict(lambda: [0, 0])
    for r in voos:
        uf_voos[(r["semana_inicio"], r["sg_uf_origem"])][0] += int(r["qtd_voos"])
        uf_voos[(r["semana_inicio"], r["sg_uf_origem"])][1] += int(r["nr_passageiros"])

    tr_br = defaultdict(dict)
    tr_uf = {}
    for r in trends:
        v = num(r["valor"])
        if r["geo"] == "BR" and (r["grupo"], r["termo"]) in SERIES_TRENDS_BR:
            tr_br[r["semana_inicio"]][SERIES_TRENDS_BR[(r["grupo"], r["termo"])]] = v
        if r["geo"] == "BR" and r["grupo"] == "contexto_viagem" and r["termo"] == "curso de inglês":
            tr_br[r["semana_inicio"]]["_curso_ingles_ctx"] = v
        if r["grupo"] == GRUPO_UF and r["termo"] == TERMO_UF:
            tr_uf[(r["semana_inicio"], r["sg_uf"])] = v

    # Indice composto: soma dos 5 termos de intencao (mesma escala), 100 = maior semana
    soma = {s: sum(d[t] for t in TERMOS_INTENCAO) for s, d in tr_br.items()
            if all(d.get(t) is not None for t in TERMOS_INTENCAO)}
    max_soma = max(soma.values())
    max_pax = max(br[s]["nr_passageiros"] for s in br if cal[s]["semana_completa"] == "true")

    semanas = sorted(set(cal) & set(tr_br))
    tabela_br = []
    for s in semanas:
        b, t = br[s], tr_br[s]
        linha = dict(cal[s])
        linha["evento"] = ", ".join(por_semana.get(s, []))
        linha.update({k: int(b[k]) for k in ["qtd_voos", "nr_passageiros", "voos_eua", "voos_canada",
                                             "voos_reino_unido", "pax_eua", "pax_canada",
                                             "pax_reino_unido"]})
        linha["pax_por_voo"] = round(b["nr_passageiros"] / b["qtd_voos"], 1) if b["qtd_voos"] else None
        linha["pax_indice"] = round(100 * b["nr_passageiros"] / max_pax, 2)
        for col in SERIES_TRENDS_BR.values():
            linha[col] = t.get(col)
        linha["tr_intencao_ingles"] = round(100 * soma[s] / max_soma, 2) if s in soma else None
        ctx, online = t.get("_curso_ingles_ctx"), t.get("tr_curso_online")
        linha["tr_razao_ingles_curso_online"] = round(100 * ctx / online, 2) if ctx and online else None
        tabela_br.append(linha)

    # Semana x UF: UFs com voo comercial ou com serie semanal no Trends
    ufs_voo = {u for _, u in uf_voos}
    ufs_tr = {u for _, u in tr_uf}
    tabela_uf = []
    for s in semanas:
        for u in sorted(ufs_voo | ufs_tr):
            q, p = uf_voos.get((s, u), [0, 0])
            v = tr_uf.get((s, u))
            c = cal[s]
            tabela_uf.append({
                **{k: c[k] for k in ["semana_inicio", "semana_fim", "ano_semana", "num_semana",
                                     "mes_referencia", "temporada", "semana_completa"]},
                "sg_uf": u, "nome_uf": UFS[u][0], "regiao": UFS[u][1],
                "qtd_voos": q, "nr_passageiros": p, "tr_curso_ingles_uf": v,
                "tem_dado_trends": "true" if v is not None else "false",
                "cruzamento": "voos e trends" if u in ufs_voo and u in ufs_tr
                else ("so voos" if u in ufs_voo else "so trends"),
            })

    # Correlacoes: Brasil e cada UF com as duas series
    completas = [s for s in semanas if cal[s]["semana_completa"] == "true"]
    series_voos = {n: {l["semana_inicio"]: l[n] for l in tabela_br} for n in SERIES_VOOS_BR}
    series_tr = {n: {l["semana_inicio"]: l[n] for l in tabela_br} for n in SERIES_TRENDS_CORR}
    tabela_corr = correlacoes("BR", series_voos, series_tr, completas)
    pearson_uf = {}
    for u in sorted(ufs_voo & ufs_tr):
        sx = {"nr_passageiros": {s: uf_voos.get((s, u), [0, 0])[1] for s in completas},
              "qtd_voos": {s: uf_voos.get((s, u), [0, 0])[0] for s in completas}}
        sy = {"tr_curso_ingles_uf": {s: tr_uf.get((s, u)) for s in completas}}
        linhas = correlacoes(u, sx, sy, completas)
        tabela_corr += linhas
        zero = [l for l in linhas if l[1] == "nr_passageiros" and l[3] == "nivel" and l[4] == 0]
        if zero:
            pearson_uf[u] = (zero[0][5], zero[0][7])

    # Resumo por UF
    total_pax = sum(p for (s, _), (_, p) in uf_voos.items())
    interesse = {r["sg_uf"]: num(r["valor"]) for r in mapa if r["termo"] == TERMO_UF}
    resumo = []
    for u in sorted(UFS):
        q = sum(v[0] for (s, uu), v in uf_voos.items() if uu == u and s in semanas)
        p = sum(v[1] for (s, uu), v in uf_voos.items() if uu == u and s in semanas)
        com_dado = sum(1 for (s, uu), v in tr_uf.items() if uu == u and v is not None)
        r, n = pearson_uf.get(u, (None, None))
        resumo.append({"sg_uf": u, "nome_uf": UFS[u][0], "regiao": UFS[u][1], "qtd_voos": q,
                       "nr_passageiros": p, "pct_passageiros": round(100 * p / total_pax, 2),
                       "interesse_curso_ingles": interesse.get(u),
                       "serie_semanal_trends": "true" if u in ufs_tr else "false",
                       "semanas_com_dado_trends": com_dado, "pearson_semanal": r, "pares_semanal": n})
    return tabela_br, tabela_uf, resumo, tabela_corr


# ------------------------------------------------------------------- escrita
def csv_bytes(colunas, linhas):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(colunas)
    for l in linhas:
        w.writerow(["" if (v := (l[c] if isinstance(l, dict) else l[i])) is None else v
                    for i, c in enumerate(colunas)])
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
    br, uf, resumo, corr = montar(ler(spark, f"{silver}/voos_semanal"),
                                  ler(spark, f"{silver}/voos_semanal_uf"),
                                  ler(spark, f"{silver}/google_trends_semanal"),
                                  ler(spark, f"{silver}/google_trends_mapa_uf"))
    print(f"Brasil: {len(br)} semanas; UF: {len(uf)} linhas; correlacoes: {len(corr)}")
    gravar(csv_bytes(COLUNAS_BR, br), gold, "cruzamento_semanal_br")
    gravar(csv_bytes(COLUNAS_UF, uf), gold, "cruzamento_semanal_uf")
    gravar(csv_bytes(COLUNAS_RESUMO, resumo), gold, "resumo_uf")
    gravar(csv_bytes(COLUNAS_CORR, corr), gold, "correlacoes")


def main():
    if "--local" in sys.argv:
        i = sys.argv.index("--local")
        silver, gold = sys.argv[i + 1], sys.argv[i + 2]
        spark = SparkSession.builder.appName("cruzamento_voos_trends").getOrCreate()
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
