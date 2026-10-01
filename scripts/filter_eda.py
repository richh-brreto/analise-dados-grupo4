"""
Gera a base de entrada da EDA (SPTech_Notebook_EDA) a partir dos 19 CSVs
mensais limpos, sem nunca carregar um mes inteiro em memoria.

Mesmo recorte de filter_ingles.py (origem BRASIL, destino EUA/Canada/Reino
Unido), mas SEM agregar: cada linha continua sendo um registro da ANAC (um
par de aeroportos dentro de um voo). A EDA precisa do grao original para
enxergar nulos, outliers e a propria questao do grao.

Diferencas em relacao a filter_ingles.py:
  - voos de carga e sem passageiros sao mantidos (sao uma subpopulacao que
    a EDA deve encontrar, nao algo a esconder antes dela)
  - apenas as colunas de COLUNAS_SAIDA sao gravadas
  - data e hora de partida viram uma unica coluna dh_partida_real, para a
    secao de sazonalidade por hora do notebook funcionar. Ela e gravada
    como DD/MM/AAAA HH:MM:SS porque o notebook converte datas com
    dayfirst=True: em ISO (AAAA-MM-DD) o pandas trocaria dia e mes
  - ds_cotran entra na saida porque faz parte do grao: o mesmo trecho de
    um voo aparece em ate tres linhas, uma por tipo de movimento
    (desembarque, conexao domestica, conexao internacional)

Entrada: data/combinadaYYYY-MM/combinadaYYYY-MM.csv
Saida:   data/base_eda_ingles.csv (Latin-1, ';')
"""
import csv
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUT_PATH = os.path.join(DATA_DIR, "base_eda_ingles.csv")
ENCODING = "latin-1"
DELIMITER = ";"

PAIS_ORIGEM = "BRASIL"
PAISES_DESTINO_INGLES = {
    "ESTADOS UNIDOS DA AMÉRICA",
    "CANADÁ",
    "REINO UNIDO",
}

COL_DATA_PARTIDA = "dt_partida_real"
COL_HORA_PARTIDA = "hr_partida_real"
COL_DH_PARTIDA = "dh_partida_real"

COLUNAS_SAIDA = [
    "id_combinada",
    "sg_empresa_icao",
    "nr_voo",
    COL_DH_PARTIDA,
    "sg_icao_origem",
    "sg_icao_destino",
    "ds_cotran",
    "nr_etapa",
    "nr_escala_destino",
    "nr_passag_pagos",
    "nr_passag_gratis",
    "kg_bagagem_livre",
    "kg_carga_paga",
    "kg_bagagem_excesso",
    "kg_carga_gratis",
    "kg_correio",
    "nm_empresa",
    "ds_tipo_empresa",
    "ds_grupo_di",
    "ds_servico_tipo_linha",
    "nm_municipio_origem",
    "sg_uf_origem",
    "nm_municipio_destino",
    "nm_pais_destino",
]

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


def data_br(data, hora):
    data, hora = data.strip(), hora.strip()
    if len(data) == 10 and data[4] == "-":
        data = f"{data[8:10]}/{data[5:7]}/{data[0:4]}"
    return f"{data} {hora}".strip()


def main():
    files = find_csv_files()
    if not files:
        raise SystemExit("Nenhum CSV limpo encontrado em " + DATA_DIR)

    header = None
    total_in = total_out = 0

    with open(OUT_PATH, "w", encoding=ENCODING, newline="") as fout:
        writer = csv.writer(fout, delimiter=DELIMITER, quotechar='"',
                            quoting=csv.QUOTE_MINIMAL)
        writer.writerow(COLUNAS_SAIDA)

        for name, path in files:
            with open(path, "r", encoding=ENCODING, newline="") as fin:
                reader = csv.reader(fin, delimiter=DELIMITER, quotechar='"')
                h = next(reader)
                if header is None:
                    header = h
                    pos = {c: i for i, c in enumerate(header)}
                    faltando = [c for c in COLUNAS_SAIDA
                                if c != COL_DH_PARTIDA and c not in pos]
                    if faltando:
                        raise ValueError(f"Colunas ausentes na origem: {faltando}")
                    i_origem = pos["nm_pais_origem"]
                    i_destino = pos["nm_pais_destino"]
                    i_data = pos[COL_DATA_PARTIDA]
                    i_hora = pos[COL_HORA_PARTIDA]
                elif h != header:
                    raise ValueError(f"Cabecalho diferente em {name}")

                n_in = n_out = 0
                for row in reader:
                    n_in += 1
                    if row[i_origem] != PAIS_ORIGEM:
                        continue
                    if row[i_destino] not in PAISES_DESTINO_INGLES:
                        continue
                    n_out += 1

                    dh = data_br(row[i_data], row[i_hora])
                    writer.writerow([dh if c == COL_DH_PARTIDA else row[pos[c]]
                                     for c in COLUNAS_SAIDA])

            total_in += n_in
            total_out += n_out
            print(f"[{name}] {n_in} linhas -> {n_out} mantidas", flush=True)

    print(f"\nTotal: {total_in} linhas lidas, {total_out} gravadas "
          f"({len(COLUNAS_SAIDA)} colunas)")
    print(f"Arquivo: {OUT_PATH}")


if __name__ == "__main__":
    main()
