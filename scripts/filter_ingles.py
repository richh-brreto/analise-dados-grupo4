"""
Filtra os CSVs mensais (ja limpos) para manter somente voos comerciais de
passageiros saindo do Brasil com destino a paises de lingua inglesa (Estados
Unidos, Canada e Reino Unido) e agrega o resultado por ano e mes.

Na etapa combinada da ANAC cada linha e um par de aeroportos (embarque x
desembarque) dentro de um voo, e nao um voo. Um voo com escala gera mais de
uma linha com origem Brasil e destino no mesmo pais. Por isso as linhas
filtradas sao primeiro somadas ao voo a que pertencem (identificado por
empresa ICAO, numero do voo e data de partida real) e so depois cada voo
entra, uma unica vez, na agregacao por ano e mes. O nr_singular fica fora da
chave porque costuma vir vazio.

Cada voo e classificado a partir do tipo de servico da linha e do total de
passageiros embarcados (somando todos os pares de aeroportos):
  - "voo de carga/reabastecimento": servico da linha CARGUEIRO ou nenhum
    passageiro a bordo (voo de posicionamento/ferry sem carga)
  - "voo comercial": voo de linha com pelo menos um passageiro a bordo

Somente os voos comerciais entram no arquivo de saida; os de carga sao
apenas contados no resumo do console, porque nao interessam para a analise
de demanda por aulas de ingles.

Saida (uma linha por ano x mes):
  ano, mes, estacao, temporada, qtd_voos, nr_passageiros

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
VOO_COLS = ["sg_empresa_icao", "nr_voo", "dt_partida_real"]
SERVICO_COL = "ds_servico_tipo_linha"
SERVICO_CARGUEIRO = "CARGUEIRO"

TIPO_CARGA = "voo de carga/reabastecimento"
TIPO_COMERCIAL = "voo comercial"

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


def classificar(pax, servico):
    if servico == SERVICO_CARGUEIRO or pax == 0:
        return TIPO_CARGA
    return TIPO_COMERCIAL


def main():
    files = find_csv_files()
    if not files:
        raise SystemExit("Nenhum CSV limpo encontrado em " + DATA_DIR)

    header = None
    idx_origem = idx_destino = idx_mes = None
    idx_pax = idx_voo = idx_servico = None
    total_in = 0
    total_out = 0
    voos = {}

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
                idx_voo = [header.index(c) for c in VOO_COLS]
                idx_servico = header.index(SERVICO_COL) if SERVICO_COL in header else None
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

                chave_voo = tuple(row[i] for i in idx_voo)
                voo = voos.get(chave_voo)
                if voo is None:
                    ano_mes = row[idx_mes]
                    servico = row[idx_servico] if idx_servico is not None else ""
                    voo = {"ano": int(ano_mes[:4]), "mes": int(ano_mes[4:]), "pax": 0, "servico": servico}
                    voos[chave_voo] = voo
                voo["pax"] += sum(to_int(row[i]) for i in idx_pax)

            total_in += n_in
            total_out += n_out
            print(f"[{name}] {n_in} linhas -> {n_out} mantidas", flush=True)

    aggregates = {}
    n_carga = 0
    for voo in voos.values():
        if classificar(voo["pax"], voo["servico"]) == TIPO_CARGA:
            n_carga += 1
            continue
        bucket = aggregates.setdefault((voo["ano"], voo["mes"]), {"qtd_voos": 0, "nr_passageiros": 0})
        bucket["qtd_voos"] += 1
        bucket["nr_passageiros"] += voo["pax"]

    with open(OUT_PATH, "w", encoding=ENCODING, newline="") as fout:
        writer = csv.writer(fout, delimiter=DELIMITER, quotechar='"', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(
            ["ano", "mes", "estacao", "temporada", "qtd_voos", "nr_passageiros"]
        )
        for ano, mes in sorted(aggregates):
            b = aggregates[(ano, mes)]
            writer.writerow([
                ano,
                mes,
                ESTACAO_POR_MES[mes],
                TEMPORADA_POR_MES[mes],
                b["qtd_voos"],
                b["nr_passageiros"],
            ])

    n_comercial = sum(b["qtd_voos"] for b in aggregates.values())
    n_pax = sum(b["nr_passageiros"] for b in aggregates.values())
    print(f"\nTotal geral: {total_in} linhas lidas, {total_out} linhas mantidas, {len(voos)} voos distintos EUA/Canada/Reino Unido")
    print(f"Voos de carga/reabastecimento excluidos: {n_carga}")
    print(f"Voos comerciais gravados: {n_comercial} ({n_pax} passageiros)")
    print(f"Linhas agregadas (ano x mes): {len(aggregates)}")
    print(f"Arquivo consolidado: {OUT_PATH}")


if __name__ == "__main__":
    main()
