"""
Agrega os voos comerciais do Brasil para Estados Unidos, Canada e Reino Unido
por semana, com o recorte regional do aeroporto de embarque (UF e municipio).

Entrada: data/base_eda_ingles.csv
  registros da ANAC (etapas combinadas) ja filtrados para origem Brasil e
  destino EUA, Canada ou Reino Unido. Latin-1, separador ';'.
Saidas, UTF-8, separador ';':
  data/silver/voos_semanal_uf/voos_semanal_uf_parte0001.csv
    uma linha por semana x UF x municipio x pais de destino
  data/silver/voos_semanal/voos_semanal_parte0001.csv
    uma linha por semana x pais de destino (Brasil inteiro, voos sem dupla
    contagem: um voo com embarque em dois aeroportos conta uma vez)
  Mesmos arquivos, nos mesmos caminhos relativos, que o job
  glue_bronze_para_silver.py grava no bucket silver a partir dos arquivos
  brutos (data/ espelha os buckets).

A semana vai de domingo a sabado, igual a semana do Google Trends, para que
semana_inicio sirva de chave no cruzamento. As regras de voo (chave, exclusao
de cargueiros) sao as mesmas de scripts/filter_ingles.py e do job
glue_bronze_para_silver.py; ver METODOLOGIA.md, secoes 4 e 9.

Tambem aceita a base com todos os destinos (base_eda_internacional.csv, de
filter_eda.py): nesse caso so as linhas com grupo_destino = RECORTE entram, e
registros repetidos entre arquivos mensais contam uma vez.

Uso:
  python scripts/voos_semanal.py
  python scripts/voos_semanal.py ../analise-pi/data/base_eda_internacional.csv
"""
import csv
import datetime as dt
import os
import statistics
import sys
from collections import defaultdict

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ENTRADA = os.path.join(BASE_DIR, "data", "base_eda_ingles.csv")
SILVER = os.path.join(BASE_DIR, "data", "silver")
SAIDA = os.path.join(SILVER, "voos_semanal_uf", "voos_semanal_uf_parte0001.csv")
SAIDA_BR = os.path.join(SILVER, "voos_semanal", "voos_semanal_parte0001.csv")
ENCODING = "latin-1"        # da entrada; a saida e UTF-8

SERVICO_CARGUEIRO = "CARGUEIRO"
PAX_COLS = ["nr_passag_pagos", "nr_passag_gratis"]
CHAVE_REGISTRO = ["sg_empresa_icao", "nr_voo", "dh_partida_real", "sg_icao_origem",
                  "sg_icao_destino", "nr_escala_destino", "ds_cotran"]
# Um mes so conta como coberto se tiver ao menos esta fracao da mediana mensal
# de voos. Isola meses residuais, como os 2 voos de 01/08/2026.
FRACAO_MES_COBERTO = 0.5

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
COLUNAS_SAIDA = COLUNAS_CALENDARIO + [
    "sg_uf_origem", "nm_municipio_origem", "nm_pais_destino", "qtd_voos", "nr_passageiros",
]
COLUNAS_SAIDA_BR = COLUNAS_CALENDARIO + ["nm_pais_destino", "qtd_voos", "nr_passageiros"]


def inicio_semana(data):
    """Domingo da semana (domingo a sabado) que contem a data."""
    return data - dt.timedelta(days=(data.weekday() + 1) % 7)


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


def numero(valor):
    try:
        return float(valor.replace(",", "."))
    except (AttributeError, ValueError):
        return 0.0


def ler_voos(caminho):
    """Soma os registros ao voo (empresa, numero, data de partida)."""
    voos, vistos = {}, set()
    with open(caminho, encoding=ENCODING, newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            if linha.get("grupo_destino", "RECORTE") != "RECORTE":
                continue
            chave_reg = tuple(linha[c] for c in CHAVE_REGISTRO)
            if chave_reg in vistos:
                continue
            vistos.add(chave_reg)
            data = dt.datetime.strptime(linha["dh_partida_real"], "%d/%m/%Y %H:%M:%S").date()
            chave = (linha["sg_empresa_icao"], linha["nr_voo"], data)
            voo = voos.setdefault(chave, {"data": data, "pax": 0.0, "cargueiro": False,
                                           "pais": linha["nm_pais_destino"], "embarques": defaultdict(float)})
            pax = sum(numero(linha[c]) for c in PAX_COLS)
            voo["pax"] += pax
            voo["cargueiro"] |= linha["ds_servico_tipo_linha"] == SERVICO_CARGUEIRO
            voo["embarques"][(linha["sg_uf_origem"], linha["nm_municipio_origem"])] += pax
    return voos


def dias_cobertos_por_semana(voos):
    """Dias de cada semana dentro dos meses cobertos pela base."""
    por_mes = defaultdict(int)
    for v in voos.values():
        por_mes[(v["data"].year, v["data"].month)] += 1
    corte = FRACAO_MES_COBERTO * statistics.median(por_mes.values())
    meses = {m for m, n in por_mes.items() if n >= corte}

    cobertura = defaultdict(int)
    for ano, mes in meses:
        dia = dt.date(ano, mes, 1)
        while dia.month == mes:
            cobertura[inicio_semana(dia)] += 1
            dia += dt.timedelta(days=1)
    return cobertura


def linha_calendario(semana, cobertura):
    dias = cobertura.get(semana, 0)
    linha = atributos_semana(semana)
    linha.update({"dias_cobertos": dias, "semana_completa": "true" if dias == 7 else "false"})
    return linha


def agregar(voos):
    """Devolve (linhas por aeroporto de embarque, linhas do Brasil inteiro)."""
    cobertura = dias_cobertos_por_semana(voos)
    grupos = defaultdict(lambda: [0, 0])
    nacional = defaultdict(lambda: [0, 0])
    for v in voos.values():
        if v["cargueiro"] or v["pax"] <= 0:
            continue
        semana = inicio_semana(v["data"])
        nacional[(semana, v["pais"])][0] += 1
        nacional[(semana, v["pais"])][1] += v["pax"]
        for (uf, municipio), pax in v["embarques"].items():
            g = grupos[(semana, uf, municipio, v["pais"])]
            g[0] += 1          # voo com embarque neste aeroporto
            g[1] += pax

    linhas = []
    for (semana, uf, municipio, pais), (qtd, pax) in sorted(grupos.items()):
        linha = linha_calendario(semana, cobertura)
        linha.update({"sg_uf_origem": uf, "nm_municipio_origem": municipio, "nm_pais_destino": pais,
                      "qtd_voos": qtd, "nr_passageiros": int(round(pax))})
        linhas.append(linha)
    linhas_br = []
    for (semana, pais), (qtd, pax) in sorted(nacional.items()):
        linha = linha_calendario(semana, cobertura)
        linha.update({"nm_pais_destino": pais, "qtd_voos": qtd, "nr_passageiros": int(round(pax))})
        linhas_br.append(linha)
    return linhas, linhas_br


def gravar(caminho, colunas, linhas):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=colunas, delimiter=";", lineterminator="\n")
        w.writeheader()
        w.writerows(linhas)
    print(f"Linhas gravadas: {len(linhas)} em {os.path.relpath(caminho, BASE_DIR)}")


def main():
    entrada = sys.argv[1] if len(sys.argv) > 1 else ENTRADA
    voos = ler_voos(entrada)
    linhas, linhas_br = agregar(voos)
    gravar(SAIDA, COLUNAS_SAIDA, linhas)
    gravar(SAIDA_BR, COLUNAS_SAIDA_BR, linhas_br)

    comerciais = [v for v in voos.values() if not v["cargueiro"] and v["pax"] > 0]
    semanas = sorted({l["semana_inicio"] for l in linhas_br})
    completas = sorted({l["semana_inicio"] for l in linhas_br if l["semana_completa"] == "true"})
    print(f"Voos lidos: {len(voos)}; comerciais: {len(comerciais)} "
          f"({int(sum(v['pax'] for v in comerciais))} passageiros)")
    print(f"Semanas: {len(semanas)} ({semanas[0]} a {semanas[-1]}); completas: {len(completas)}")


if __name__ == "__main__":
    main()
