"""
Envia as partes geradas por scripts/chunk_arquivos.py para a Lambda que grava
no bucket (Function URL), substituindo o loop com curl.

Cada parte vai no corpo de um POST, com o destino no parametro filename:
  POST <url>?filename=<nome>/<nome>_parte0001.csv

A URL da Lambda vem de --url, da variavel de ambiente LAMBDA_URL ou do .env
na raiz do repositorio (LAMBDA_URL=...):
  export LAMBDA_URL="https://xxxx.lambda-url.us-east-1.on.aws/"
  python scripts/enviar_chunks.py                      # todas as pastas de data/chunks
  python scripts/enviar_chunks.py combinada2025-01     # so algumas pastas
  python scripts/enviar_chunks.py data/chunks/combinada2025-01/combinada2025-01_parte0003.csv

Regras:
  - cada envio e tentado ate --tentativas vezes, com espera crescente
  - partes que falharem sao listadas em falhas.log (um caminho por linha),
    que pode ser passado de volta com --reenviar falhas.log
  - o codigo de saida e 1 se alguma parte falhar
"""
import argparse
import glob
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CHUNKS_DIR = os.path.join(BASE_DIR, "data", "chunks")
LOG_FALHAS = os.path.join(BASE_DIR, "falhas.log")
TENTATIVAS_PADRAO = 3
TIMEOUT_S = 60


def carregar_env(caminho=os.path.join(BASE_DIR, ".env")):
    """Le CHAVE=valor do .env da raiz; variaveis ja definidas no shell tem prioridade."""
    if not os.path.isfile(caminho):
        return
    with open(caminho) as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.removeprefix("export ").split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip("'\""))


def listar_partes(alvos):
    """Resolve pastas (nome ou caminho) e arquivos em uma lista de partes .csv."""
    if not alvos:
        alvos = sorted(os.path.join(CHUNKS_DIR, d) for d in os.listdir(CHUNKS_DIR))
    partes = []
    for alvo in alvos:
        if not os.path.exists(alvo) and os.path.isdir(os.path.join(CHUNKS_DIR, alvo)):
            alvo = os.path.join(CHUNKS_DIR, alvo)
        if os.path.isdir(alvo):
            partes += sorted(glob.glob(os.path.join(alvo, "*_parte*.csv")))
        elif os.path.isfile(alvo):
            partes.append(alvo)
        else:
            sys.exit(f"Nao encontrado: {alvo}")
    return partes


def chave_destino(caminho):
    """<pasta>/<arquivo>, igual ao filename usado no curl."""
    pasta = os.path.basename(os.path.dirname(os.path.abspath(caminho)))
    return f"{pasta}/{os.path.basename(caminho)}"


def enviar(url, caminho, tentativas):
    chave = chave_destino(caminho)
    destino = f"{url}?{urllib.parse.urlencode({'filename': chave})}"
    with open(caminho, "rb") as f:
        corpo = f.read()

    for tentativa in range(1, tentativas + 1):
        req = urllib.request.Request(
            destino, data=corpo, method="POST",
            # mesmo Content-Type que curl --data-binary
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                resp.read()
                return None
        except urllib.error.HTTPError as e:
            erro = f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}"
            if 400 <= e.code < 500 and e.code != 429:
                return erro  # erro do cliente: repetir nao adianta
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            erro = str(getattr(e, "reason", e))
        if tentativa < tentativas:
            time.sleep(2 * tentativa)
    return erro


def main():
    carregar_env()
    parser = argparse.ArgumentParser(description="Envia as partes de data/chunks para a Lambda.")
    parser.add_argument("alvos", nargs="*",
                        help="pastas (ex.: combinada2025-01) ou partes .csv (padrao: tudo em data/chunks)")
    parser.add_argument("--url", default=os.environ.get("LAMBDA_URL"),
                        help="Function URL da Lambda (padrao: $LAMBDA_URL)")
    parser.add_argument("--tentativas", type=int, default=TENTATIVAS_PADRAO,
                        help=f"tentativas por parte (padrao: {TENTATIVAS_PADRAO})")
    parser.add_argument("--reenviar", metavar="LOG",
                        help="reenvia apenas as partes listadas em um falhas.log anterior")
    parser.add_argument("--dry-run", action="store_true",
                        help="so lista o que seria enviado")
    args = parser.parse_args()

    if not args.url and not args.dry_run:
        sys.exit("Informe a URL da Lambda com --url ou LAMBDA_URL.")
    url = (args.url or "").rstrip("/") + "/"

    if args.reenviar:
        with open(args.reenviar) as f:
            partes = [linha.strip() for linha in f if linha.strip()]
    else:
        partes = listar_partes(args.alvos)
    if not partes:
        sys.exit("Nenhuma parte encontrada. Rode antes scripts/chunk_arquivos.py.")

    falhas = []
    for i, caminho in enumerate(partes, 1):
        prefixo = f"[{i}/{len(partes)}] {chave_destino(caminho)}"
        if args.dry_run:
            print(prefixo)
            continue
        erro = enviar(url, caminho, args.tentativas)
        if erro:
            falhas.append(os.path.abspath(caminho))
            print(f"{prefixo} FALHOU ({erro})", flush=True)
        else:
            print(f"{prefixo} ok", flush=True)

    if args.dry_run:
        return
    print(f"\nTotal: {len(partes) - len(falhas)} enviadas, {len(falhas)} falhas")
    if falhas:
        with open(LOG_FALHAS, "w") as f:
            f.write("\n".join(falhas) + "\n")
        print(f"Partes com falha em {os.path.relpath(LOG_FALHAS)} "
              f"(reenvie com --reenviar {os.path.relpath(LOG_FALHAS)})")
        sys.exit(1)


if __name__ == "__main__":
    main()
