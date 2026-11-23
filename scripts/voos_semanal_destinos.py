"""
Grupo de comparacao: voos comerciais semanais do Brasil para TODOS os destinos
internacionais, separados em anglofono (o recorte do projeto: EUA, Canada,
Reino Unido), outro anglofono e nao anglofono, e por continente de destino.

Serve para separar o efeito das ferias (viagem internacional em geral) do
efeito do destino de lingua inglesa. Fica numa tabela propria para nao
misturar com o recorte do projeto (voos_semanal e voos_semanal_uf).

Entrada: data/base_eda_internacional.csv (ou o caminho passado como argumento)
  Base da EDA gerada por filter_eda.py no workspace analise-pi: todos os
  registros com origem Brasil e destino no exterior, Latin-1, separador ';'.
  Nao e versionada (52 MB); copie de analise-pi/data/.
Saida:   data/silver/voos_semanal_destinos/voos_semanal_destinos_parte0001.csv
  UTF-8, separador ';', uma linha por semana x grupo de destino x continente.

Regras (METODOLOGIA.md, secao 15): as mesmas do recorte (chave do voo,
exclusao de cargueiros e de voos sem passageiro), aplicadas dentro de cada
grupo x continente. As 6 linhas repetidas entre arquivos mensais, todas de
destinos nao anglofonos, entram uma vez so.

Uso:
  python scripts/voos_semanal_destinos.py
  python scripts/voos_semanal_destinos.py ../analise-pi/data/base_eda_internacional.csv
"""
import csv
import datetime as dt
import os
import statistics
import sys
from collections import defaultdict

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ENTRADA = os.path.join(BASE_DIR, "data", "base_eda_internacional.csv")
SAIDA = os.path.join(BASE_DIR, "data", "silver", "voos_semanal_destinos",
                     "voos_semanal_destinos_parte0001.csv")
ENCODING = "latin-1"

SERVICO_CARGUEIRO = "CARGUEIRO"
PAX_COLS = ["nr_passag_pagos", "nr_passag_gratis"]
CHAVE_REGISTRO = ["sg_empresa_icao", "nr_voo", "dh_partida_real", "sg_icao_origem",
                  "sg_icao_destino", "nr_escala_destino", "ds_cotran"]
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
COLUNAS = [
    "semana_inicio", "semana_fim", "ano_semana", "num_semana", "mes_referencia",
    "estacao", "temporada", "dias_cobertos", "semana_completa",
    "grupo_destino", "nm_continente_destino", "qtd_voos", "nr_passageiros",
]


def inicio_semana(data):
    return data - dt.timedelta(days=(data.weekday() + 1) % 7)


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


def numero(valor):
    try:
        return float(valor.replace(",", "."))
    except (AttributeError, ValueError):
        return 0.0


def ler_voos(caminho):
    """Soma os registros ao voo dentro de cada grupo de destino x continente."""
    vistos, repetidos = set(), 0
    voos = {}
    with open(caminho, encoding=ENCODING, newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            chave_reg = tuple(linha[c] for c in CHAVE_REGISTRO)
            if chave_reg in vistos:
                repetidos += 1
                continue
            vistos.add(chave_reg)
            data = dt.datetime.strptime(linha["dh_partida_real"], "%d/%m/%Y %H:%M:%S").date()
            segmento = (linha["grupo_destino"], linha["nm_continente_destino"])
            chave = (segmento, linha["sg_empresa_icao"], linha["nr_voo"], data)
            voo = voos.setdefault(chave, {"data": data, "pax": 0.0, "cargueiro": False})
            voo["pax"] += sum(numero(linha[c]) for c in PAX_COLS)
            voo["cargueiro"] |= linha["ds_servico_tipo_linha"] == SERVICO_CARGUEIRO
    print(f"Linhas repetidas descartadas: {repetidos}")
    return voos


def dias_cobertos(voos):
    por_mes = defaultdict(set)
    for (seg, emp, nr, data), v in voos.items():
        por_mes[(data.year, data.month)].add((emp, nr, data))
    contagem = {m: len(s) for m, s in por_mes.items()}
    corte = FRACAO_MES_COBERTO * statistics.median(contagem.values())
    cobertura = defaultdict(int)
    for (ano, mes), n in contagem.items():
        if n < corte:
            continue
        dia = dt.date(ano, mes, 1)
        while dia.month == mes:
            cobertura[inicio_semana(dia)] += 1
            dia += dt.timedelta(days=1)
    return cobertura


def agregar(voos):
    cobertura = dias_cobertos(voos)
    grupos = defaultdict(lambda: [0, 0.0])
    for ((grupo, continente), _, _, data), v in voos.items():
        if v["cargueiro"] or v["pax"] <= 0:
            continue
        g = grupos[(inicio_semana(data), grupo, continente)]
        g[0] += 1
        g[1] += v["pax"]
    linhas = []
    for (semana, grupo, continente), (qtd, pax) in sorted(grupos.items()):
        dias = cobertura.get(semana, 0)
        linha = atributos_semana(semana)
        linha.update({"dias_cobertos": dias, "semana_completa": "true" if dias == 7 else "false",
                      "grupo_destino": grupo, "nm_continente_destino": continente,
                      "qtd_voos": qtd, "nr_passageiros": int(round(pax))})
        linhas.append(linha)
    return linhas


def main():
    entrada = sys.argv[1] if len(sys.argv) > 1 else ENTRADA
    if not os.path.exists(entrada):
        sys.exit(f"Base nao encontrada: {entrada}. Copie base_eda_internacional.csv de analise-pi/data/ "
                 "ou passe o caminho como argumento.")
    linhas = agregar(ler_voos(entrada))
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, delimiter=";", lineterminator="\n")
        w.writeheader()
        w.writerows(linhas)

    totais = defaultdict(lambda: [0, 0])
    for l in linhas:
        totais[l["grupo_destino"]][0] += l["qtd_voos"]
        totais[l["grupo_destino"]][1] += l["nr_passageiros"]
    for g, (q, p) in sorted(totais.items()):
        print(f"  {g:16s} {q:7d} voos  {p:10d} passageiros")
    print(f"Linhas gravadas: {len(linhas)} em {os.path.relpath(SAIDA, BASE_DIR)}")


if __name__ == "__main__":
    main()
