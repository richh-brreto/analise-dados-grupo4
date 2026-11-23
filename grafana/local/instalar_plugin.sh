#!/usr/bin/env bash
# Baixa a versao mais recente do plugin DuckDB para o Grafana (motherduck-duckdb-datasource)
# para grafana/local/plugins/. Rode uma vez, antes do docker compose up.
set -euo pipefail
cd "$(dirname "$0")"
API=https://api.github.com/repos/motherduckdb/grafana-duckdb-datasource/releases/latest
URL=$(curl -fsSL "$API" | python -c 'import json, sys
r = json.load(sys.stdin)
zips = [a["browser_download_url"] for a in r["assets"] if a["name"].endswith(".zip")]
print(zips[0] if zips else "")')
[[ -n "$URL" ]] || { echo "Nenhum .zip na ultima release; baixe manualmente da pagina de releases."; exit 1; }
echo "Baixando $URL"
curl -fL -o plugin.zip "$URL"
rm -rf plugins/motherduck-duckdb-datasource && mkdir -p plugins
python - <<'PY'
import os, shutil, zipfile
destino = "plugins/motherduck-duckdb-datasource"
with zipfile.ZipFile("plugin.zip") as z:
    z.extractall("plugins/_tmp")
raiz = next(d for d, _, fs in os.walk("plugins/_tmp") if "plugin.json" in fs)
shutil.move(raiz, destino)
shutil.rmtree("plugins/_tmp", ignore_errors=True)
for f in os.listdir(destino):
    if f.startswith("gpx_"):
        os.chmod(os.path.join(destino, f), 0o755)
print("Plugin em", destino, "->", sorted(f for f in os.listdir(destino) if f.startswith("gpx_")))
PY
rm -f plugin.zip
