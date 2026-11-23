#!/usr/bin/env bash
# Roda o pipeline local inteiro, da ANAC bruta ao PDF dos graficos.
#
# Uso, a partir da raiz do repositorio, com o venv ativado:
#   bash rodar_pipeline_local.sh                 # tudo
#   bash rodar_pipeline_local.sh --sem-anac      # pula a limpeza da ANAC (usa a base ja gerada)
#   bash rodar_pipeline_local.sh --sem-trends    # pula a coleta do Trends (usa o bronze atual)
#
# Variavel opcional: ANALISE_PI (padrao ../analise-pi), onde ficam os arquivos da ANAC
# e os scripts clean_combinada.py e filter_eda.py.
set -euo pipefail
cd "$(dirname "$0")"

ANALISE_PI="${ANALISE_PI:-../analise-pi}"
BASE="$ANALISE_PI/data/base_eda_internacional.csv"
SEM_ANAC=0; SEM_TRENDS=0
for a in "$@"; do
  case "$a" in
    --sem-anac) SEM_ANAC=1 ;;
    --sem-trends) SEM_TRENDS=1 ;;
    *) echo "Opcao desconhecida: $a"; exit 1 ;;
  esac
done

INICIO_TOTAL=$SECONDS
etapa() { echo; echo "== [$(date +%H:%M:%S)] $*"; }

# ------------------------------------------------------------ pre-requisitos
etapa "Conferindo Java e Hadoop (para os jobs do Glue em modo local)"
JAVA_MAIOR=$(java -version 2>&1 | sed -n 's/.*version "\([0-9]*\).*/\1/p' | head -1)
if [[ -z "$JAVA_MAIOR" || "$JAVA_MAIOR" -lt 17 ]]; then
  echo "Precisa de Java 17 ou mais novo no PATH (achei: ${JAVA_MAIOR:-nenhum})."; exit 1
fi
echo "  Java $JAVA_MAIOR"
if [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* ]]; then
  if [[ -z "${HADOOP_HOME:-}" ]] || ! command -v winutils.exe >/dev/null; then
    echo "No Windows o Spark precisa de HADOOP_HOME e do winutils.exe/hadoop.dll no PATH."
    echo "Veja as linhas de export no ~/.bashrc (grafana/README.md e conversa de configuracao)."; exit 1
  fi
  echo "  HADOOP_HOME=$HADOOP_HOME"
fi

# ------------------------------------------------------------------- ANAC
if [[ $SEM_ANAC -eq 0 ]]; then
  etapa "ANAC: descompactando os meses que ainda estao em .zip"
  (cd "$ANALISE_PI/data" && python - <<'PY'
import glob, os, zipfile
for z in sorted(glob.glob("combinada????-??.zip")):
    nome = z[:-4]
    if os.path.isfile(os.path.join(nome, nome + ".txt")):
        continue
    os.makedirs(nome, exist_ok=True)
    with zipfile.ZipFile(z) as arq:
        arq.extractall(nome)
    print("  descompactado", nome)
PY
  )
  etapa "ANAC: limpeza dos arquivos mensais (clean_combinada.py; a etapa mais demorada)"
  (cd "$ANALISE_PI" && python scripts/clean_combinada.py)
  etapa "ANAC: base com todos os destinos internacionais (filter_eda.py)"
  (cd "$ANALISE_PI" && python scripts/filter_eda.py | tail -3)
fi
[[ -f "$BASE" ]] || { echo "Base nao encontrada: $BASE"; exit 1; }

etapa "Voos semanais: recorte (EUA, Canada, Reino Unido) e grupo de comparacao"
python scripts/voos_semanal.py "$BASE"
python scripts/voos_semanal_destinos.py "$BASE"

# --------------------------------------------------------------- Trends
if [[ $SEM_TRENDS -eq 0 ]]; then
  read -r INICIO FIM < <(python - <<'PY'
import csv
with open("data/silver/voos_semanal/voos_semanal_parte0001.csv", encoding="utf-8") as f:
    l = list(csv.DictReader(f, delimiter=";"))
print(min(r["semana_inicio"] for r in l), max(r["semana_fim"] for r in l))
PY
  )
  INICIO="${INICIO//$'\r'/}"; FIM="${FIM//$'\r'/}"      # o Python do Windows termina a linha com \r\n
  etapa "Google Trends: coleta de $INICIO a $FIM (alguns minutos, com pausas entre chamadas)"
  NOVO="data/bronze_nova_coleta"
  rm -rf "$NOVO"
  python scripts/coletar_google_trends.py --inicio "$INICIO" --fim "$FIM" --saida "$NOVO"
  ARQ="data/bronze_arquivo/google_trends_$(date +%Y%m%d_%H%M%S)"
  mkdir -p "$(dirname "$ARQ")"
  [[ -d data/bronze/google_trends ]] && mv data/bronze/google_trends "$ARQ" && echo "  coleta anterior guardada em $ARQ"
  mkdir -p data/bronze
  mv "$NOVO" data/bronze/google_trends
fi

# ------------------------------------------------------- Glue em modo local
mkdir -p logs
spark() {                       # nome_do_log script argumentos...
  local log="logs/$1.log"; shift
  if ! python "$@" > "$log" 2>&1; then
    echo "  FALHOU. Final do log ($log):"; tail -25 "$log"; exit 1
  fi
  grep -E "^(Emenda|Series|Brasil|Semanal|Gravado)" "$log" | sed 's/^/  /'
}

etapa "Trends: bronze -> silver"
spark trends_silver scripts/glue_trends_bronze_para_silver.py --local data/bronze data/silver
etapa "Cruzamento: silver -> gold"
spark gold scripts/glue_silver_para_gold.py --local data/silver data/gold
etapa "Grupo de comparacao: silver -> gold"
spark destinos_gold scripts/glue_destinos_silver_para_gold.py --local data/silver data/gold

# ------------------------------------------------------ analise e entregas
etapa "Testes de hipoteses e graficos"
python scripts/analise_hipoteses.py > /dev/null
python scripts/analise_destinos.py > /dev/null
echo "  graficos em graficos/cruzamento e graficos/comparacao_destinos"

etapa "Dashboard do Grafana (Athena e local) e teste das consultas"
python scripts/gerar_dashboard_grafana.py
python scripts/testar_consultas_grafana.py

etapa "PDF dos graficos"
python scripts/gerar_pdf_graficos.py

echo
echo "Pipeline concluido em $(( (SECONDS - INICIO_TOTAL) / 60 )) min."
