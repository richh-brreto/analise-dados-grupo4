"""
Job do AWS Glue (Spark) que junta a limpeza e o filtro dos dados combinados
da ANAC: le as partes do bucket bronze e grava no bucket silver os agregados
de voos comerciais de passageiros do Brasil para Estados Unidos, Canada e
Reino Unido, em duas granularidades:

  mensal (Brasil inteiro), mantida para compatibilidade com a EDA;
  semanal (Brasil inteiro e por aeroporto de embarque: UF e municipio), por
  pais de destino, usada no cruzamento com o Google Trends.

Entrada (bronze): combinadaYYYY-MM/combinadaYYYY-MM_parteNNNN.csv
  Latin-1, separador ';', campos entre aspas, cabecalho em todas as partes.
Saida (silver), UTF-8, separador ';':
  voos_brasil_paises_ingleses/voos_brasil_paises_ingleses_parte0001.csv
    ano, mes, estacao, temporada, qtd_voos, nr_passageiros
  voos_semanal/voos_semanal_parte0001.csv
    semana_inicio, semana_fim, ano_semana, num_semana, mes_referencia,
    estacao, temporada, dias_cobertos, semana_completa, nm_pais_destino,
    qtd_voos, nr_passageiros
  voos_semanal_uf/voos_semanal_uf_parte0001.csv
    as mesmas colunas de calendario, mais sg_uf_origem, nm_municipio_origem,
    nm_pais_destino, qtd_voos, nr_passageiros

A semana vai de domingo a sabado, como no Google Trends. Ver METODOLOGIA.md,
secoes 4 e 9.

Parametros do job no Glue: --BRONZE_BUCKET e --SILVER_BUCKET (so o nome).

Execucao local, para teste, com pastas no mesmo formato dos buckets:
  python glue_bronze_para_silver.py --local <pasta_bronze> <pasta_silver>
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
NOME_MENSAL = "voos_brasil_paises_ingleses"
NOME_SEMANAL = "voos_semanal"
NOME_SEMANAL_UF = "voos_semanal_uf"

PAIS_ORIGEM = "BRASIL"
PAISES_DESTINO = ["ESTADOS UNIDOS DA AMÉRICA", "CANADÁ", "REINO UNIDO"]
SERVICO_CARGUEIRO = "CARGUEIRO"
FRACAO_MES_COBERTO = 0.5

VOO_COLS = ["sg_empresa_icao", "nr_voo", "dt_partida_real"]
PAX_COLS = ["nr_passag_pagos", "nr_passag_gratis"]
ORIGEM_COLS = ["sg_uf_origem", "nm_municipio_origem"]
COLUNAS = VOO_COLS + PAX_COLS + ORIGEM_COLS + [
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
COLUNAS_CALENDARIO = [
    "semana_inicio", "semana_fim", "ano_semana", "num_semana", "mes_referencia",
    "estacao", "temporada", "dias_cobertos", "semana_completa",
]
COLUNAS_SEMANAL = COLUNAS_CALENDARIO + ["nm_pais_destino", "qtd_voos", "nr_passageiros"]
COLUNAS_SEMANAL_UF = COLUNAS_CALENDARIO + [
    "sg_uf_origem", "nm_municipio_origem", "nm_pais_destino", "qtd_voos", "nr_passageiros",
]
SEMANA = "semana_inicio"


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


def voos_filtrados(df):
    """Registros do recorte com a data de partida e os passageiros do trecho."""
    pax = sum(F.coalesce(F.col(c).cast("double"), F.lit(0.0)) for c in PAX_COLS)
    # A ANAC publica a data como AAAA-MM-DD; o formato brasileiro fica como reserva.
    data = F.coalesce(F.to_date("dt_partida_real", "yyyy-MM-dd"),
                      F.to_date("dt_partida_real", "dd/MM/yyyy"))
    return (
        df.where((F.col("nm_pais_origem") == PAIS_ORIGEM) & F.col("nm_pais_destino").isin(PAISES_DESTINO))
        .withColumn("pax_trecho", pax)
        .withColumn("data_partida", data)
    )


def por_voo(regs):
    return (
        regs.groupBy(*VOO_COLS)
        .agg(
            F.min("nr_ano_mes_partida_real").alias("ano_mes"),
            F.min("data_partida").alias("data_partida"),
            F.first("nm_pais_destino").alias("nm_pais_destino"),
            F.sum("pax_trecho").alias("pax"),
            F.max((F.col("ds_servico_tipo_linha") == SERVICO_CARGUEIRO).cast("int")).alias("cargueiro"),
        )
        .withColumn("comercial", (F.coalesce(F.col("cargueiro"), F.lit(0)) == 0) & (F.col("pax") > 0))
    )


def agregar_mensal(voos):
    return (
        voos.groupBy(
            F.substring("ano_mes", 1, 4).cast("int").alias("ano"),
            F.substring("ano_mes", 5, 2).cast("int").alias("mes"),
            "comercial",
        )
        .agg(F.count("*").alias("qtd_voos"), F.sum("pax").alias("nr_passageiros"))
        .collect()
    )


def domingo(col):
    return F.expr(f"date_sub({col}, dayofweek({col}) - 1)")


def agregar_semanal(voos):
    """Voos comerciais por semana x pais de destino, Brasil inteiro."""
    return (
        voos.where("comercial")
        .groupBy(domingo("data_partida").alias(SEMANA), "nm_pais_destino")
        .agg(F.count("*").alias("qtd_voos"), F.sum("pax").alias("nr_passageiros"))
        .collect()
    )


def agregar_semanal_uf(regs, voos):
    """Voos comerciais por semana x aeroporto de embarque x pais de destino.

    Um voo com embarques em dois aeroportos conta uma vez em cada um; os
    passageiros sao os embarcados naquele aeroporto, entao somam exatamente o
    total nacional.
    """
    embarques = regs.groupBy(*VOO_COLS, *ORIGEM_COLS).agg(F.sum("pax_trecho").alias("pax_trecho"))
    comerciais = voos.where("comercial").select(*VOO_COLS, "data_partida", "nm_pais_destino")
    return (
        embarques.join(comerciais, VOO_COLS)
        .groupBy(domingo("data_partida").alias(SEMANA), *ORIGEM_COLS, "nm_pais_destino")
        .agg(F.count("*").alias("qtd_voos"), F.sum("pax_trecho").alias("nr_passageiros"))
        .collect()
    )


def meses_cobertos(voos):
    """Meses com ao menos metade da mediana mensal de voos (todos os tipos)."""
    contagem = {(r["ano"], r["mes"]): r["n"] for r in (
        voos.groupBy(F.year("data_partida").alias("ano"), F.month("data_partida").alias("mes"))
        .agg(F.count("*").alias("n")).collect())}
    corte = FRACAO_MES_COBERTO * statistics.median(contagem.values())
    return {m for m, n in contagem.items() if n >= corte}


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
    """Ano e numero da semana pela quarta-feira (regra da semana epidemiologica)."""
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


def csv_bytes(colunas, linhas):
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\n")
    writer.writerow(colunas)
    writer.writerows(linhas)
    return buf.getvalue().encode("utf-8")


def montar_mensal(linhas):
    comerciais = sorted((r for r in linhas if r["comercial"]), key=lambda r: (r["ano"], r["mes"]))
    conteudo = csv_bytes(
        ["ano", "mes", "estacao", "temporada", "qtd_voos", "nr_passageiros"],
        [[r["ano"], r["mes"], ESTACAO_POR_MES[r["mes"]], TEMPORADA_POR_MES[r["mes"]],
          r["qtd_voos"], int(r["nr_passageiros"])] for r in comerciais])

    n_carga = sum(r["qtd_voos"] for r in linhas if not r["comercial"])
    n_voos = sum(r["qtd_voos"] for r in comerciais)
    n_pax = sum(r["nr_passageiros"] for r in comerciais)
    print(f"Voos de carga/reabastecimento excluidos: {n_carga}")
    print(f"Voos comerciais: {n_voos} ({int(n_pax)} passageiros) em {len(comerciais)} meses")
    return conteudo


def montar_semanal(linhas, meses, colunas, chaves):
    cobertura = dias_cobertos(meses)
    saida = []
    for r in sorted(linhas, key=lambda r: tuple([r[SEMANA]] + [r[c] or "" for c in chaves])):
        dias = cobertura.get(r[SEMANA], 0)
        a = atributos_semana(r[SEMANA])
        a.update({c: r[c] for c in chaves})
        a.update({"dias_cobertos": dias, "semana_completa": "true" if dias == 7 else "false",
                  "qtd_voos": r["qtd_voos"], "nr_passageiros": int(round(r["nr_passageiros"]))})
        saida.append([a[c] for c in colunas])
    semanas = {r[0] for r in saida}
    completas = {r[0] for r in saida if r[8] == "true"}
    print(f"Semanal por {chaves}: {len(saida)} linhas, {len(semanas)} semanas "
          f"({len(completas)} completas)")
    return csv_bytes(colunas, saida)


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
    regs = voos_filtrados(ler_bronze(spark, bronze)).cache()
    voos = por_voo(regs).cache()
    gravar(montar_mensal(agregar_mensal(voos)), silver, NOME_MENSAL)
    meses = meses_cobertos(voos)
    gravar(montar_semanal(agregar_semanal(voos), meses, COLUNAS_SEMANAL, ["nm_pais_destino"]),
           silver, NOME_SEMANAL)
    gravar(montar_semanal(agregar_semanal_uf(regs, voos), meses, COLUNAS_SEMANAL_UF,
                          ORIGEM_COLS + ["nm_pais_destino"]), silver, NOME_SEMANAL_UF)


def main():
    if "--local" in sys.argv:
        i = sys.argv.index("--local")
        bronze, silver = sys.argv[i + 1], sys.argv[i + 2]
        spark = SparkSession.builder.appName(NOME_MENSAL).getOrCreate()
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
