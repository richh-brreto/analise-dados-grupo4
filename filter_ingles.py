"""
Filtra os CSVs mensais (ja limpos) para manter somente voos saindo do Brasil
com destino a paises de lingua inglesa (Estados Unidos, Canada e Reino Unido)
e agrega o resultado por ano, mes e tipo de voo.

Saida (uma linha por ano x mes x tipo_voo):
  ano, mes, estacao, temporada, tipo_voo, qtd_voos, nr_passageiros

O tipo_voo substitui as colunas de peso de bagagem/carga por uma
classificacao discreta, derivada do numero de passageiros embarcados:
  - "voo de carga/reabastecimento": nenhum passageiro a bordo (voo cargueiro
    ou voo de posicionamento/ferry sem carga)
  - "voo privado": de 1 a 19 passageiros (faixa da aviacao executiva /
    aeronaves de pequeno porte)
  - "voo de turismo": 20 ou mais passageiros (voo comercial de passageiros)

As colunas estacao e temporada enriquecem o mes com contexto de calendario.
Como os voos PARTEM do Brasil, e o calendario brasileiro (hemisferio sul) que
explica a demanda -- nos destinos (EUA/Canada/Reino Unido) as estacoes sao
invertidas.
  - estacao: estacoes meteorologicas do hemisferio sul, em blocos de
    trimestre (dez-fev verao, mar-mai outono, jun-ago inverno,
    set-nov primavera)
  - temporada: momento do calendario escolar brasileiro, que e o principal
    motor das viagens de lazer (ferias escolares, volta as aulas,
    periodo letivo)
"""
import csv
import os
from collections import OrderedDict

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUT_PATH = os.path.join(DATA_DIR, "voos_brasil_paises_ingleses.csv")
ENCODING = "latin-1"
DELIMITER = ";"

PAIS_ORIGEM = "BRASIL"
PAISES_DESTINO_INGLES = {
    "ESTADOS UNIDOS DA AMÉRICA",
    "CANADÁ",
    "REINO UNIDO",
}

MES_COL = "nr_ano_mes_partida_real"
PAX_COLS = ["nr_passag_pagos", "nr_passag_gratis"]

TIPO_CARGA = "voo de carga/reabastecimento"
TIPO_PRIVADO = "voo privado"
TIPO_TURISMO = "voo de turismo"
ORDEM_TIPOS = [TIPO_PRIVADO, TIPO_TURISMO, TIPO_CARGA]

LIMITE_PRIVADO = 19  # ate 19 assentos = aviacao executiva / pequeno porte

# Estacoes do hemisferio sul (Brasil, origem dos voos), por trimestre
ESTACAO_POR_MES = {
    12: "verão", 1: "verão", 2: "verão",
    3: "outono", 4: "outono", 5: "outono",
    6: "inverno", 7: "inverno", 8: "inverno",
    9: "primavera", 10: "primavera", 11: "primavera",
}

# Calendario escolar brasileiro: principal motor das viagens de lazer
TEMPORADA_POR_MES = {
    1: "férias escolares",    # ferias de verao
    2: "volta às aulas",
    3: "período letivo",
    4: "período letivo",
    5: "período letivo",
    6: "período letivo",
    7: "férias escolares",    # ferias de meio de ano
    8: "volta às aulas",
    9: "período letivo",
    10: "período letivo",
    11: "período letivo",
    12: "férias escolares",   # ferias de fim de ano / Natal
}

csv.field_size_limit(10_000_000)


def find_csv_files():
    files = []
    for entry in sorted(os.listdir(DATA_DIR)):
        folder = os.path.join(DATA_DIR, entry)
        if not os.path.isdir(folder):
            continue
        csv_path = os.path.join(folder, entry + ".csv")
        if os.path.isfile(csv_path):
            files.append((entry, csv_path))
    return files


def to_int(val):
    if not val:
        return 0
    return int(float(val))


def classificar(pax):
    if pax == 0:
        return TIPO_CARGA
    if pax <= LIMITE_PRIVADO:
        return TIPO_PRIVADO
    return TIPO_TURISMO


def main():
    files = find_csv_files()
    if not files:
        raise SystemExit("Nenhum CSV limpo encontrado em " + DATA_DIR)

    header = None
    idx_origem = idx_destino = idx_mes = None
    idx_pax = None
    total_in = 0
    total_out = 0
    aggregates = OrderedDict()  # (ano, mes, tipo) -> {"qtd_voos", "nr_passageiros"}

    for name, path in files:
        with open(path, "r", encoding=ENCODING, newline="") as fin:
            reader = csv.reader(fin, delimiter=DELIMITER, quotechar='"')
            h = next(reader)
            if header is None:
                header = h
                idx_origem = header.index("nm_pais_origem")
                idx_destino = header.index("nm_pais_destino")
                idx_mes = header.index(MES_COL)
                idx_pax = [header.index(c) for c in PAX_COLS]
            elif h != header:
                raise ValueError(f"Cabecalho diferente em {name}")

            n_in = n_out = 0
            for row in reader:
                n_in += 1
                if row[idx_origem] != PAIS_ORIGEM:
                    continue
                if row[idx_destino] not in PAISES_DESTINO_INGLES:
                    continue
                n_out += 1

                ano_mes = row[idx_mes]
                ano, mes = int(ano_mes[:4]), int(ano_mes[4:])
                pax = sum(to_int(row[i]) for i in idx_pax)
                chave = (ano, mes, classificar(pax))

                bucket = aggregates.setdefault(chave, {"qtd_voos": 0, "nr_passageiros": 0})
                bucket["qtd_voos"] += 1
                bucket["nr_passageiros"] += pax

            total_in += n_in
            total_out += n_out
            print(f"[{name}] {n_in} linhas -> {n_out} mantidas", flush=True)

    with open(OUT_PATH, "w", encoding=ENCODING, newline="") as fout:
        writer = csv.writer(fout, delimiter=DELIMITER, quotechar='"', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(
            ["ano", "mes", "estacao", "temporada", "tipo_voo", "qtd_voos", "nr_passageiros"]
        )
        for ano, mes, tipo in sorted(
            aggregates, key=lambda k: (k[0], k[1], ORDEM_TIPOS.index(k[2]))
        ):
            b = aggregates[(ano, mes, tipo)]
            writer.writerow([
                ano,
                mes,
                ESTACAO_POR_MES[mes],
                TEMPORADA_POR_MES[mes],
                tipo,
                b["qtd_voos"],
                b["nr_passageiros"],
            ])

    print(f"\nTotal geral: {total_in} linhas lidas, {total_out} voos EUA/Canada/Reino Unido")
    print(f"Linhas agregadas (ano x mes x tipo): {len(aggregates)}")
    print(f"Arquivo consolidado: {OUT_PATH}")


if __name__ == "__main__":
    main()
