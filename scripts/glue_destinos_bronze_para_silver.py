"""
Job do AWS Glue (Spark) do grupo de comparacao: le as partes brutas da ANAC no
bucket bronze e grava no silver os voos comerciais semanais do Brasil para
TODOS os destinos internacionais, por grupo de destino (RECORTE = EUA, Canada,
Reino Unido; OUTRO ANGLOFONO; NAO ANGLOFONO) e continente.

Fica separado de glue_bronze_para_silver.py para nao misturar o grupo de
comparacao com o recorte do projeto.

Entrada (bronze): combinadaYYYY-MM/combinadaYYYY-MM_parteNNNN.csv
  Latin-1, separador ';', campos entre aspas, cabecalho em todas as partes.
Saida (silver), UTF-8, separador ';':
  voos_semanal_destinos/voos_semanal_destinos_parte0001.csv
    semana_inicio, semana_fim, ano_semana, num_semana, mes_referencia,
    estacao, temporada, dias_cobertos, semana_completa, grupo_destino,
    nm_continente_destino, qtd_voos, nr_passageiros

Regras (METODOLOGIA.md, secao 15): as do recorte (chave do voo, exclusao de
cargueiros e de voos sem passageiro), aplicadas dentro de cada grupo x
continente; registros repetidos entre arquivos mensais entram uma vez so.

Parametros do job no Glue: --BRONZE_BUCKET e --SILVER_BUCKET (so o nome).

Execucao local, para teste, com pastas no mesmo formato dos buckets:
  python glue_destinos_bronze_para_silver.py --local <pasta_bronze> <pasta_silver>
"""
import csv
import datetime as dt
import io
import os
import statistics
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

PADRAO_ENTRADA = "combinada*/combinada*_parte*.csv"
NOME = "voos_semanal_destinos"

PAIS_ORIGEM = "BRASIL"
RECORTE = ["ESTADOS UNIDOS DA AMÉRICA", "CANADÁ", "REINO UNIDO"]
OUTROS_ANGLOFONOS = [
    "ÁFRICA DO SUL", "JAMAICA", "GUIANA", "TRINIDAD E TOBAGO", "SANTA LÚCIA",
    "BARBADOS", "BAHAMAS", "ANTÍGUA E BARBUDA", "NIGÉRIA", "QUÊNIA", "GANA",
    "LIBÉRIA", "MALTA", "SINGAPURA", "IRLANDA", "AUSTRÁLIA", "NOVA ZELÂNDIA",
    "ZÂMBIA", "TANZÂNIA", "BOTSUANA",
]
SERVICO_CARGUEIRO = "CARGUEIRO"
FRACAO_MES_COBERTO = 0.5

VOO_COLS = ["sg_empresa_icao", "nr_voo", "dt_partida_real"]
PAX_COLS = ["nr_passag_pagos", "nr_passag_gratis"]
CHAVE_REGISTRO = ["sg_empresa_icao", "nr_voo", "dt_partida_real", "hr_partida_real",
                  "sg_icao_origem", "sg_icao_destino", "nr_escala_destino", "ds_cotran"]
COLUNAS = sorted(set(CHAVE_REGISTRO + PAX_COLS + [
    "ds_servico_tipo_linha", "nm_pais_origem", "nm_pais_destino", "nm_continente_destino"]))
SEGMENTO = ["grupo_destino", "nm_continente_destino"]

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
COLUNAS_SAIDA = [
    "semana_inicio", "semana_fim", "ano_semana", "num_semana", "mes_referencia",
    "estacao", "temporada", "dias_cobertos", "semana_completa",
    "grupo_destino", "nm_continente_destino", "qtd_voos", "nr_passageiros",
]


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


def por_voo(df):
    pax = sum(F.coalesce(F.col(c).cast("double"), F.lit(0.0)) for c in PAX_COLS)
    data = F.coalesce(F.to_date("dt_partida_real", "yyyy-MM-dd"),
                      F.to_date("dt_partida_real", "dd/MM/yyyy"))
    grupo = (F.when(F.col("nm_pais_destino").isin(RECORTE), "RECORTE")
             .when(F.col("nm_pais_destino").isin(OUTROS_ANGLOFONOS), "OUTRO ANGLÓFONO")
             .otherwise("NÃO ANGLÓFONO"))
    regs = (
        df.where((F.col("nm_pais_origem") == PAIS_ORIGEM)
                 & (F.col("nm_pais_destino") != PAIS_ORIGEM)
                 & F.col("nm_pais_destino").isNotNull())
        .dropDuplicates(CHAVE_REGISTRO)
        .withColumn("grupo_destino", grupo)
        .withColumn("pax_trecho", pax)
        .withColumn("data_partida", data)
    )
    return (
        regs.groupBy(*SEGMENTO, *VOO_COLS)
        .agg(F.min("data_partida").alias("data_partida"),
             F.sum("pax_trecho").alias("pax"),
             F.max((F.col("ds_servico_tipo_linha") == SERVICO_CARGUEIRO).cast("int")).alias("cargueiro"))
        .withColumn("comercial", (F.coalesce(F.col("cargueiro"), F.lit(0)) == 0) & (F.col("pax") > 0))
    )


def meses_cobertos(voos):
    contagem = {(r["ano"], r["mes"]): r["n"] for r in (
        voos.select(*VOO_COLS, "data_partida").distinct()
        .groupBy(F.year("data_partida").alias("ano"), F.month("data_partida").alias("mes"))
        .agg(F.count("*").alias("n")).collect())}
    corte = FRACAO_MES_COBERTO * statistics.median(contagem.values())
    return {m for m, n in contagem.items() if n >= corte}


def agregar(voos):
    semana = F.expr("date_sub(data_partida, dayofweek(data_partida) - 1)")
    return (
        voos.where("comercial")
        .groupBy(semana.alias("semana_inicio"), *SEGMENTO)
        .agg(F.count("*").alias("qtd_voos"), F.sum("pax").alias("nr_passageiros"))
        .collect()
    )


def inicio_semana(data):
    return data - dt.timedelta(days=(data.weekday() + 1) % 7)


def dias_cobertos(meses):
    cobertura = {}
    for ano, mes in meses:
        dia = dt.date(ano, mes, 1)
        while dia.month == mes:
            s = inicio_semana(dia)
            cobertura[s] = cobertura.get(s, 0) + 1
            dia += dt.timedelta(days=1)
    return cobertura


def atributos_semana(inicio):
    quarta = inicio + dt.timedelta(days=3)
    return {
        "semana_inicio": inicio.isoformat(),
        "semana_fim": (inicio + dt.timedelta(days=6)).isoformat(),
        "ano_semana": quarta.year,
        "num_semana": (quarta.timetuple().tm_yday - 1) // 7 + 1,
        "mes_referencia": quarta.month,
        "estacao": ESTACAO_POR_MES[quarta.month],
        "temporada": TEMPORADA_POR_MES[quarta.month],
    }


def montar(linhas, meses):
    cobertura = dias_cobertos(meses)
    saida = []
    for r in sorted(linhas, key=lambda r: (r["semana_inicio"], r["grupo_destino"],
                                           r["nm_continente_destino"] or "")):
        dias = cobertura.get(r["semana_inicio"], 0)
        a = atributos_semana(r["semana_inicio"])
        a.update({"dias_cobertos": dias, "semana_completa": "true" if dias == 7 else "false",
                  "grupo_destino": r["grupo_destino"], "nm_continente_destino": r["nm_continente_destino"],
                  "qtd_voos": r["qtd_voos"], "nr_passageiros": int(round(r["nr_passageiros"]))})
        saida.append([a[c] for c in COLUNAS_SAIDA])
    print(f"Semanal por destino: {len(saida)} linhas")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(COLUNAS_SAIDA)
    w.writerows(saida)
    return buf.getvalue().encode("utf-8")


def gravar(conteudo, raiz):
    chave = f"{NOME}/{NOME}_parte0001.csv"
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
    voos = por_voo(ler_bronze(spark, bronze)).cache()
    gravar(montar(agregar(voos), meses_cobertos(voos)), silver)


def main():
    if "--local" in sys.argv:
        i = sys.argv.index("--local")
        bronze, silver = sys.argv[i + 1], sys.argv[i + 2]
        spark = SparkSession.builder.appName(NOME).getOrCreate()
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
