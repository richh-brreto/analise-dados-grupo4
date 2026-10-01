"""
Job do AWS Glue (Spark) que junta a limpeza e o filtro dos dados combinados
da ANAC: le as partes do bucket bronze e grava no bucket silver o agregado
mensal de voos comerciais de passageiros do Brasil para Estados Unidos,
Canada e Reino Unido.

Entrada (bronze): combinadaYYYY-MM/combinadaYYYY-MM_parteNNNN.csv
  Latin-1, separador ';', campos entre aspas, cabecalho em todas as partes.
Saida (silver):   voos_brasil_paises_ingleses/voos_brasil_paises_ingleses_parte0001.csv
  UTF-8, separador ';', colunas:
  ano, mes, estacao, temporada, qtd_voos, nr_passageiros

Parametros do job no Glue: --BRONZE_BUCKET e --SILVER_BUCKET (so o nome).

Execucao local, para teste, com pastas no mesmo formato dos buckets:
  python glue_bronze_para_silver.py --local <pasta_bronze> <pasta_silver>
"""
import csv
import io
import os
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

PADRAO_ENTRADA = "combinada*/combinada*_parte*.csv"
NOME_SAIDA = "voos_brasil_paises_ingleses"

PAIS_ORIGEM = "BRASIL"
PAISES_DESTINO = ["ESTADOS UNIDOS DA AMÉRICA", "CANADÁ", "REINO UNIDO"]
SERVICO_CARGUEIRO = "CARGUEIRO"

VOO_COLS = ["sg_empresa_icao", "nr_voo", "dt_partida_real"]
PAX_COLS = ["nr_passag_pagos", "nr_passag_gratis"]
COLUNAS = VOO_COLS + PAX_COLS + [
    "nr_ano_mes_partida_real",
    "ds_servico_tipo_linha",
    "nm_pais_origem",
    "nm_pais_destino",
]

ESTACAO_POR_MES = {
    12: "verão", 1: "verão", 2: "verão",
    3: "outono", 4: "outono", 5: "outono",
    6: "inverno", 7: "inverno", 8: "inverno",
    9: "primavera", 10: "primavera", 11: "primavera",
}
TEMPORADA_POR_MES = {
    1: "férias escolares", 2: "volta às aulas",
    3: "período letivo", 4: "período letivo", 5: "período letivo", 6: "período letivo",
    7: "férias escolares", 8: "volta às aulas",
    9: "período letivo", 10: "período letivo", 11: "período letivo",
    12: "férias escolares",
}


def ler_bronze(spark, raiz):
    return (
        spark.read
        .option("header", True)
        .option("sep", ";")
        .option("quote", '"')
        .option("escape", '"')
        .option("encoding", "ISO-8859-1")
        .csv(f"{raiz.rstrip('/')}/{PADRAO_ENTRADA}")
        .select(*COLUNAS)
    )


def agregar(df):
    pax = sum(F.coalesce(F.col(c).cast("double"), F.lit(0.0)) for c in PAX_COLS).cast("long")

    voos = (
        df.where((F.col("nm_pais_origem") == PAIS_ORIGEM) & F.col("nm_pais_destino").isin(PAISES_DESTINO))
        .groupBy(*VOO_COLS)
        .agg(
            F.min("nr_ano_mes_partida_real").alias("ano_mes"),
            F.sum(pax).alias("pax"),
            F.max((F.col("ds_servico_tipo_linha") == SERVICO_CARGUEIRO).cast("int")).alias("cargueiro"),
        )
        .withColumn("comercial", (F.coalesce(F.col("cargueiro"), F.lit(0)) == 0) & (F.col("pax") > 0))
    )

    return (
        voos.groupBy(
            F.substring("ano_mes", 1, 4).cast("int").alias("ano"),
            F.substring("ano_mes", 5, 2).cast("int").alias("mes"),
            "comercial",
        )
        .agg(F.count("*").alias("qtd_voos"), F.sum("pax").alias("nr_passageiros"))
        .collect()
    )


def montar_csv(linhas):
    comerciais = sorted((r for r in linhas if r["comercial"]), key=lambda r: (r["ano"], r["mes"]))
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\n")
    writer.writerow(["ano", "mes", "estacao", "temporada", "qtd_voos", "nr_passageiros"])
    for r in comerciais:
        writer.writerow([r["ano"], r["mes"], ESTACAO_POR_MES[r["mes"]], TEMPORADA_POR_MES[r["mes"]],
                         r["qtd_voos"], r["nr_passageiros"]])

    n_carga = sum(r["qtd_voos"] for r in linhas if not r["comercial"])
    n_voos = sum(r["qtd_voos"] for r in comerciais)
    n_pax = sum(r["nr_passageiros"] for r in comerciais)
    print(f"Voos de carga/reabastecimento excluidos: {n_carga}")
    print(f"Voos comerciais: {n_voos} ({n_pax} passageiros) em {len(comerciais)} meses")
    return buf.getvalue().encode("utf-8")


def gravar(conteudo, raiz):
    chave = f"{NOME_SAIDA}/{NOME_SAIDA}_parte0001.csv"
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
    linhas = agregar(ler_bronze(spark, bronze))
    gravar(montar_csv(linhas), silver)


def main():
    if "--local" in sys.argv:
        i = sys.argv.index("--local")
        bronze, silver = sys.argv[i + 1], sys.argv[i + 2]
        spark = SparkSession.builder.appName(NOME_SAIDA).getOrCreate()
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
