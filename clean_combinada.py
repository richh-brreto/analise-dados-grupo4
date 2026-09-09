"""
Limpeza dos arquivos combinadaYYYY-MM.txt (dados de voos combinados da ANAC):
- Le os .txt (ISO-8859-1 / Latin-1, delimitador ';', campos entre aspas)
- Padroniza os nomes das colunas restantes (lower snake_case)
- Grava um .csv por mes mantendo a codificacao Latin-1
  para preservar os acentos.
"""
import csv
import os
import re
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
ENCODING = "latin-1"
DELIMITER = ";"

csv.field_size_limit(10_000_000)


def standardize(name: str) -> str:
    name = name.strip().strip('"').strip().lower()
    name = re.sub(r"[^0-9a-z_]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name


def find_txt_files():
    files = []
    for entry in sorted(os.listdir(DATA_DIR)):
        folder = os.path.join(DATA_DIR, entry)
        if not os.path.isdir(folder):
            continue
        txt = os.path.join(folder, entry + ".txt")
        if os.path.isfile(txt):
            files.append((entry, txt))
    return files


def pass1_nonempty_mask(files):
    header = None
    nonempty = None
    for name, path in files:
        with open(path, "r", encoding=ENCODING, newline="") as f:
            reader = csv.reader(f, delimiter=DELIMITER, quotechar='"')
            h = next(reader)
            if header is None:
                header = h
                nonempty = [False] * len(h)
            elif h != header:
                raise ValueError(f"Cabecalho diferente em {name}: {h}")
            pending = sum(1 for v in nonempty if not v)
            for row in reader:
                if pending == 0:
                    break
                for i, val in enumerate(row):
                    if not nonempty[i] and val.strip() != "":
                        nonempty[i] = True
                        pending -= 1
        print(f"[pass1] {name}: ok", flush=True)
    return header, nonempty


def pass2_write_csv(files, header, nonempty):
    keep_idx = [i for i, k in enumerate(nonempty) if k]
    dropped = [header[i] for i, k in enumerate(nonempty) if not k]
    new_header = [standardize(header[i]) for i in keep_idx]

    for name, path in files:
        out_path = os.path.join(os.path.dirname(path), name + ".csv")
        with open(path, "r", encoding=ENCODING, newline="") as fin, \
             open(out_path, "w", encoding=ENCODING, newline="") as fout:
            reader = csv.reader(fin, delimiter=DELIMITER, quotechar='"')
            next(reader)
            writer = csv.writer(fout, delimiter=DELIMITER, quotechar='"',
                                 quoting=csv.QUOTE_MINIMAL)
            writer.writerow(new_header)
            n = 0
            for row in reader:
                writer.writerow([row[i] for i in keep_idx])
                n += 1
        print(f"[pass2] {name}: {n} linhas -> {out_path}", flush=True)
    return dropped


def main():
    files = find_txt_files()
    if not files:
        print("Nenhum .txt encontrado em", DATA_DIR)
        sys.exit(1)
    print(f"Encontrados {len(files)} arquivos .txt")
    header, nonempty = pass1_nonempty_mask(files)
    dropped = pass2_write_csv(files, header, nonempty)
    print("\nColunas removidas (vazias em todos os meses):")
    for c in dropped:
        print(" -", c)
    print(f"\nTotal de colunas originais: {len(header)}")
    print(f"Total de colunas mantidas: {len(header) - len(dropped)}")


if __name__ == "__main__":
    main()
