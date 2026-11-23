"""
Job do AWS Glue (Spark) que le as coletas do Google Trends no bucket bronze e
grava no bucket silver as series semanais limpas, emendadas e numa escala
unica por grupo.

Entrada (bronze), UTF-8, separador ';', gerada por coletar_google_trends.py:
  google_trends/series/<grupo>/*.csv    uma requisicao por arquivo
  google_trends/mapa_uf/*.csv           interesse por UF no periodo inteiro
  (a leitura e recursiva: partes geradas pelo chunk_arquivos.py tambem servem)

Saida (silver), UTF-8, separador ';':
  google_trends_semanal/google_trends_semanal_parte0001.csv
    grupo, termo, geo, sg_uf, semana_inicio, semana_fim, valor, tem_dado, janelas
  google_trends_mapa_uf/google_trends_mapa_uf_parte0001.csv
    termo, sg_uf, nome_uf, valor, janela_inicio, janela_fim
  google_trends_emenda/google_trends_emenda_parte0001.csv
    diagnostico da emenda entre janelas (fator e erro nas semanas repetidas)

Tratamento (METODOLOGIA.md, secao 10):
  1. Coleta repetida da mesma janela: fica a mais recente (coletado_em).
  2. tem_dado = false vira nulo, nunca zero: e volume abaixo do limiar de
     privacidade do Google, nao ausencia de busca.
  3. Emenda: cada janela vem numa escala propria (0 a 100 pelo maximo dela).
     A janela seguinte e reescalada pelo fator que iguala a soma das semanas
     repetidas, calculado com todos os termos do grupo juntos, para manter a
     proporcao entre termos. Nas semanas repetidas fica a media das janelas.
  4. Escala final: 100 = maior valor do grupo no periodo inteiro. Termos do
     mesmo grupo continuam comparaveis entre si; grupos diferentes nao.

Parametros do job no Glue: --BRONZE_BUCKET e --SILVER_BUCKET (so o nome).

Execucao local, para teste, com pastas no mesmo formato dos buckets:
  python glue_trends_bronze_para_silver.py --local data/bronze data/silver
"""
import csv
import datetime as dt
import io
import os
import sys
from collections import defaultdict

from pyspark.sql import SparkSession

PREFIXO_SERIES = "google_trends/series"
PREFIXO_MAPA = "google_trends/mapa_uf"
NOME_SEMANAL = "google_trends_semanal"
NOME_MAPA = "google_trends_mapa_uf"
NOME_EMENDA = "google_trends_emenda"

COLUNAS_SEMANAL = ["grupo", "termo", "geo", "sg_uf", "semana_inicio", "semana_fim",
                   "valor", "tem_dado", "janelas"]
COLUNAS_MAPA = ["termo", "sg_uf", "nome_uf", "valor", "janela_inicio", "janela_fim"]
COLUNAS_EMENDA = ["grupo", "janela_anterior", "janela_seguinte", "semanas_repetidas",
                  "pares_comparados", "fator", "erro_medio_abs", "erro_medio_pct"]


def ler_csv(spark, caminho):
    return (
        spark.read
        .option("header", True)
        .option("sep", ";")
        .option("encoding", "UTF-8")
        .option("recursiveFileLookup", "true")
        .csv(caminho)
        .collect()
    )


def sg_uf(geo):
    return geo.split("-", 1)[1] if geo.startswith("BR-") else ""


def ultimas_coletas(linhas, chave_janela):
    """Se a mesma janela foi coletada mais de uma vez, fica a coleta mais recente."""
    mais_recente = {}
    for r in linhas:
        k = chave_janela(r)
        mais_recente[k] = max(mais_recente.get(k, ""), r["coletado_em"])
    return [r for r in linhas if r["coletado_em"] == mais_recente[chave_janela(r)]]


def emendar_grupo(linhas):
    """Emenda as janelas de um grupo. Devolve (serie, diagnosticos).

    serie: {(termo, geo): {semana: (valor ou None, n_janelas)}}
    """
    janelas = defaultdict(dict)           # (ini, fim) -> {(termo, geo, semana): valor ou None}
    for r in linhas:
        valor = float(r["valor"]) if r["tem_dado"] == "true" and r["valor"] not in (None, "") else None
        janelas[(r["janela_inicio"], r["janela_fim"])][(r["termo"], r["geo"], r["semana_inicio"])] = valor

    ordem = sorted(janelas)
    acumulado = {k: [v, 1] for k, v in janelas[ordem[0]].items()}
    diagnosticos = []
    for anterior, seguinte in zip(ordem, ordem[1:]):
        nova = janelas[seguinte]
        repetidas = [k for k in nova if k in acumulado]
        pares = [k for k in repetidas if acumulado[k][0] and nova[k]]
        if not pares:
            raise ValueError(f"Janelas {anterior} e {seguinte} sem semana em comum com dado")
        fator = sum(acumulado[k][0] for k in pares) / sum(nova[k] for k in pares)
        erros = [abs(acumulado[k][0] - nova[k] * fator) for k in pares]
        diagnosticos.append({
            "janela_anterior": f"{anterior[0]} a {anterior[1]}",
            "janela_seguinte": f"{seguinte[0]} a {seguinte[1]}",
            "semanas_repetidas": len({k[2] for k in repetidas}),
            "pares_comparados": len(pares),
            "fator": round(fator, 4),
            "erro_medio_abs": round(sum(erros) / len(erros), 2),
            "erro_medio_pct": round(100 * sum(erros) / sum(acumulado[k][0] for k in pares), 2),
        })
        for k, v in nova.items():
            v = None if v is None else v * fator
            if k not in acumulado:
                acumulado[k] = [v, 1]
            elif v is not None and acumulado[k][0] is not None:
                anterior_v, n = acumulado[k]
                acumulado[k] = [(anterior_v * n + v) / (n + 1), n + 1]
            elif v is not None:
                acumulado[k] = [v, acumulado[k][1] + 1]

    maximo = max(v for v, _ in acumulado.values() if v is not None)
    serie = defaultdict(dict)
    for (termo, geo, semana), (v, n) in acumulado.items():
        serie[(termo, geo)][semana] = (None if v is None else round(100 * v / maximo, 2), n)
    return serie, diagnosticos


def processar_series(linhas):
    linhas = ultimas_coletas(linhas, lambda r: (r["grupo"], r["janela_inicio"], r["janela_fim"]))
    por_grupo = defaultdict(list)
    for r in linhas:
        por_grupo[r["grupo"]].append(r)

    saida, emendas = [], []
    for grupo in sorted(por_grupo):
        serie, diag = emendar_grupo(por_grupo[grupo])
        for d in diag:
            d["grupo"] = grupo
            emendas.append([d[c] for c in COLUNAS_EMENDA])
            print(f"Emenda {grupo}: {d['janela_anterior']} -> {d['janela_seguinte']}: "
                  f"fator {d['fator']}, erro medio {d['erro_medio_pct']}%")
        for (termo, geo), semanas in sorted(serie.items()):
            for semana, (valor, n) in sorted(semanas.items()):
                fim = (dt.date.fromisoformat(semana) + dt.timedelta(days=6)).isoformat()
                saida.append([grupo, termo, geo, sg_uf(geo), semana, fim,
                              "" if valor is None else valor,
                              "false" if valor is None else "true", n])
    return saida, emendas


def processar_mapa(linhas):
    linhas = ultimas_coletas(linhas, lambda r: (r["termo"], r["janela_inicio"], r["janela_fim"]))
    return [[r["termo"], sg_uf(r["geo_code"]), r["geo_nome"],
             r["valor"] if r["tem_dado"] == "true" else "", r["janela_inicio"], r["janela_fim"]]
            for r in sorted(linhas, key=lambda r: (r["termo"], r["janela_inicio"], r["geo_code"]))]


def csv_bytes(colunas, linhas):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(colunas)
    w.writerows(linhas)
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


def executar(spark, bronze, silver):
    bronze = bronze.rstrip("/")
    serie, emendas = processar_series([r.asDict() for r in ler_csv(spark, f"{bronze}/{PREFIXO_SERIES}")])
    mapa = processar_mapa([r.asDict() for r in ler_csv(spark, f"{bronze}/{PREFIXO_MAPA}")])
    print(f"Series: {len(serie)} linhas; mapa: {len(mapa)} UFs; emendas: {len(emendas)}")
    gravar(csv_bytes(COLUNAS_SEMANAL, serie), silver, NOME_SEMANAL)
    gravar(csv_bytes(COLUNAS_MAPA, mapa), silver, NOME_MAPA)
    gravar(csv_bytes(COLUNAS_EMENDA, emendas), silver, NOME_EMENDA)


def main():
    if "--local" in sys.argv:
        i = sys.argv.index("--local")
        bronze, silver = sys.argv[i + 1], sys.argv[i + 2]
        spark = SparkSession.builder.appName(NOME_SEMANAL).getOrCreate()
        executar(spark, bronze, silver)
        spark.stop()
        return

    from awsglue.context import GlueContext
    from awsglue.job import Job
    from awsglue.utils import getResolvedOptions
    from pyspark.context import SparkContext

    args = getResolvedOptions(sys.argv, ["JOB_NAME", "BRONZE_BUCKET", "SILVER_BUCKET"])
    glue = GlueContext(SparkContext.getOrCreate())
    job = Job(glue)
    job.init(args["JOB_NAME"], args)
    executar(glue.spark_session, f"s3://{args['BRONZE_BUCKET']}", f"s3://{args['SILVER_BUCKET']}")
    job.commit()


if __name__ == "__main__":
    main()
