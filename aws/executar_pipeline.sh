#!/usr/bin/env bash
# Roda o pipeline na AWS na ordem certa e espera cada etapa terminar:
#   etapa 1 (em paralelo): ANAC -> silver, destinos -> silver, Trends -> silver
#   etapa 2 (em paralelo): silver -> gold, destinos silver -> gold
# Depois baixa silver e gold para ../conferencia_aws e compara com data/.
#
# Uso, a partir da raiz do repositorio:
#   bash aws/executar_pipeline.sh            # roda tudo
#   bash aws/executar_pipeline.sh --gold     # so a etapa 2
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."
source aws/config.sh
export AWS_DEFAULT_REGION="$REGIAO"

iniciar() { aws glue start-job-run --job-name "$1" --query JobRunId --output text; }

esperar() {                     # job run_id
  local estado
  while true; do
    if ! estado=$(aws glue get-job-run --job-name "$1" --run-id "$2" --query JobRun.JobRunState --output text); then
      echo "  nao consegui consultar $1 (credencial do Academy vencida?). Run id: $2"
      return 2
    fi
    case "$estado" in
      SUCCEEDED) echo "  $1: SUCCEEDED"; return 0 ;;
      FAILED|ERROR|TIMEOUT|STOPPED)
        echo "  $1: $estado"
        aws glue get-job-run --job-name "$1" --run-id "$2" --query JobRun.ErrorMessage --output text
        echo "  log: CloudWatch, grupo /aws-glue/jobs/error, stream $2"
        return 1 ;;
    esac
    sleep 30
  done
}

etapa() {                       # titulo job1 job2 ...
  local titulo=$1; shift
  echo "== $titulo"
  local -a runs=()
  for j in "$@"; do runs+=("$(iniciar "$j")"); echo "  iniciado $j"; done
  local falhou=0 i=0
  for j in "$@"; do esperar "$j" "${runs[$i]}" || falhou=1; i=$((i + 1)); done
  return $falhou
}

if [[ "${1:-}" != "--gold" ]]; then
  etapa "Etapa 1: bronze -> silver" "$JOB_ANAC_EXISTENTE" "$JOB_DESTINOS_SILVER" "$JOB_TRENDS_SILVER"
fi
etapa "Etapa 2: silver -> gold" "$JOB_GOLD" "$JOB_DESTINOS_GOLD"

echo "== Conferencia com os arquivos locais"
DEST=../conferencia_aws
rm -rf "$DEST"
aws s3 cp "s3://$SILVER_BUCKET/" "$DEST/silver/" --recursive --exclude "*" --include "*.csv" --only-show-errors
aws s3 cp "s3://$GOLD_BUCKET/"   "$DEST/gold/"   --recursive --exclude "*" --include "*.csv" --only-show-errors
iguais=0; diferentes=0
for f in $(cd data && find silver gold -name "*_parte0001.csv"); do
  if [[ ! -f "$DEST/$f" ]]; then
    echo "  FALTA na AWS: $f"; diferentes=$((diferentes + 1))
  elif cmp -s "data/$f" "$DEST/$f"; then
    iguais=$((iguais + 1))
  else
    echo "  DIFERENTE: $f"; diferentes=$((diferentes + 1))
  fi
done
echo "  $iguais iguais, $diferentes com diferenca (detalhe: diff data/<arquivo> $DEST/<arquivo>)"
