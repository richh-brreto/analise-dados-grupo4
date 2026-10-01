"""
Divide arquivos grandes em partes de no maximo 600 KB, para que cada parte
possa ser enviada aos buckets via AWS Lambda.

Por padrao processa os arquivos brutos da ANAC (data/combinadaYYYY-MM/
combinadaYYYY-MM.txt). Tambem aceita qualquer arquivo passado como argumento:
  python scripts/chunk_arquivos.py
  python scripts/chunk_arquivos.py data/base_eda_ingles.csv
  python scripts/chunk_arquivos.py --max-kb 500 data/combinada2025-01/combinada2025-01.txt

Saida: data/chunks/<nome>/<nome>_part0001.csv, <nome>_part0002.csv, ...
(sempre .csv, inclusive para os .txt brutos, para o Glue/Athena)

Regras:
  - o tamanho maximo vale para o arquivo inteiro da parte, cabecalho incluso
    (1 KB = 1000 bytes, para ficar abaixo do limite em qualquer convencao)
  - cada parte repete o cabecalho, entao e um CSV valido por si so
  - nenhum registro e cortado ao meio, inclusive campos entre aspas que
    contenham quebra de linha
  - os bytes sao copiados sem decodificar, preservando codificacao (Latin-1
    ou UTF-8) e quebras de linha CRLF do original
"""
import argparse
import glob
import os
import sys

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_DIR = os.path.join(DATA_DIR, "chunks")
MAX_KB_PADRAO = 600
EXTENSAO_SAIDA = ".csv"


def registros(arquivo):
    pendente = b""
    for linha in arquivo:
        pendente += linha
        if pendente.count(b'"') % 2 == 0:
            yield pendente
            pendente = b""
    if pendente:
        yield pendente


def chunkear(caminho, max_bytes, out_root):
    nome = os.path.splitext(os.path.basename(caminho))[0]
    ext = EXTENSAO_SAIDA
    destino = os.path.join(out_root, nome)
    os.makedirs(destino, exist_ok=True)
    for antigo in glob.glob(os.path.join(destino, f"{nome}_part*{ext}")):
        os.remove(antigo)

    with open(caminho, "rb") as f:
        it = registros(f)
        cabecalho = next(it, None)
        if cabecalho is None:
            raise SystemExit(f"Arquivo vazio: {caminho}")
        if not cabecalho.endswith(b"\n"):
            cabecalho += b"\r\n" if b"\r\n" in cabecalho else b"\n"
        if len(cabecalho) >= max_bytes:
            raise SystemExit(f"Cabecalho de {caminho} ja passa de {max_bytes} bytes")

        partes, linhas_total, maior = 0, 0, 0
        buffer, tamanho = [], len(cabecalho)

        def gravar():
            nonlocal partes, maior
            partes += 1
            saida = os.path.join(destino, f"{nome}_part{partes:04d}{ext}")
            with open(saida, "wb") as out:
                out.write(cabecalho)
                out.writelines(buffer)
            maior = max(maior, tamanho)

        for reg in it:
            if len(cabecalho) + len(reg) > max_bytes:
                raise SystemExit(
                    f"Registro {linhas_total + 1} de {caminho} tem {len(reg)} bytes "
                    f"e nao cabe em uma parte de {max_bytes} bytes"
                )
            if tamanho + len(reg) > max_bytes:
                gravar()
                buffer, tamanho = [], len(cabecalho)
            buffer.append(reg)
            tamanho += len(reg)
            linhas_total += 1
        if buffer or partes == 0:
            gravar()

    print(f"{os.path.relpath(caminho, BASE_DIR)}: {linhas_total} registros -> "
          f"{partes} partes (maior: {maior / 1000:.1f} KB) em "
          f"{os.path.relpath(destino, BASE_DIR)}", flush=True)
    return partes, linhas_total


def arquivos_padrao():
    return sorted(glob.glob(os.path.join(DATA_DIR, "combinada*", "combinada*.txt")))


def main():
    parser = argparse.ArgumentParser(description="Divide arquivos em partes de ate N KB.")
    parser.add_argument("arquivos", nargs="*", help="arquivos a dividir (padrao: .txt brutos da ANAC)")
    parser.add_argument("--max-kb", type=int, default=MAX_KB_PADRAO,
                        help=f"tamanho maximo de cada parte em KB (padrao: {MAX_KB_PADRAO})")
    parser.add_argument("--saida", default=OUT_DIR, help="pasta de saida (padrao: data/chunks)")
    args = parser.parse_args()

    arquivos = args.arquivos or arquivos_padrao()
    if not arquivos:
        sys.exit("Nenhum arquivo encontrado. Passe o caminho como argumento.")
    max_bytes = args.max_kb * 1000

    total_partes = total_registros = 0
    for caminho in arquivos:
        partes, regs = chunkear(caminho, max_bytes, args.saida)
        total_partes += partes
        total_registros += regs
    print(f"\nTotal: {len(arquivos)} arquivo(s), {total_registros} registros, {total_partes} partes")


if __name__ == "__main__":
    main()
