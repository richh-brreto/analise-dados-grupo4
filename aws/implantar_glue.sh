#!/usr/bin/env bash
# Implanta o pipeline na AWS: sobe os scripts dos jobs e a coleta do Google
# Trends para o S3, atualiza o job que ja existe e cria (ou atualiza) os quatro
# jobs novos. Pode rodar quantas vezes quiser.
#
# Uso, a partir da raiz do repositorio:
#   bash aws/implantar_glue.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1          # Git Bash: nao converter s3://... e /... em caminho do Windows
cd "$(dirname "$0")/.."
source aws/config.sh
export AWS_DEFAULT_REGION="$REGIAO"

echo "== Conta e permissoes"
aws sts get-caller-identity --query Arn --output text
for b in "$BRONZE_BUCKET" "$SILVER_BUCKET" "$GOLD_BUCKET"; do
  aws s3api head-bucket --bucket "$b" && echo "  bucket $b ok"
done

echo "== Job existente: $JOB_ANAC_EXISTENTE"
ATUAL=$(aws glue get-job --job-name "$JOB_ANAC_EXISTENTE" --query Job.Command.ScriptLocation --output text)
echo "  aponta para $ATUAL"
aws s3 cp "$ATUAL" "../glue_bronze_para_silver.backup.py" --only-show-errors
echo "  copia de seguranca do script antigo em ../glue_bronze_para_silver.backup.py"
aws s3 cp scripts/glue_bronze_para_silver.py "$ATUAL" --only-show-errors
echo "  script novo gravado no mesmo lugar (configuracao do job mantida)"

echo "== Scripts dos jobs novos -> $SCRIPTS_S3"
for s in glue_destinos_bronze_para_silver glue_trends_bronze_para_silver \
         glue_silver_para_gold glue_destinos_silver_para_gold; do
  aws s3 cp "scripts/$s.py" "$SCRIPTS_S3/$s.py" --only-show-errors
  echo "  $s.py"
done

echo "== Coleta do Google Trends -> s3://$BRONZE_BUCKET/google_trends/"
aws s3 cp data/bronze/google_trends "s3://$BRONZE_BUCKET/google_trends/" \
  --recursive --exclude "*" --include "*.csv" --only-show-errors
aws s3 ls "s3://$BRONZE_BUCKET/google_trends/" --recursive | awk '{print "  " $4}'

ROLE_ARN=$(aws iam get-role --role-name "$GLUE_ROLE" --query Role.Arn --output text 2>/dev/null || echo "$GLUE_ROLE")

criar_ou_atualizar() {          # nome script workers args_json
  local nome=$1 script=$2 workers=$3 args=$4
  local cmd="Name=glueetl,ScriptLocation=$SCRIPTS_S3/$script.py,PythonVersion=3"
  local comum=(--role "$ROLE_ARN" --command "$cmd" --glue-version "$GLUE_VERSION"
               --worker-type "$WORKER_TYPE" --number-of-workers "$workers" --timeout "$TIMEOUT_MIN"
               --default-arguments "$args")
  if aws glue get-job --job-name "$nome" >/dev/null 2>&1; then
    local upd
    upd=$(printf '{"Role":"%s","Command":{"Name":"glueetl","ScriptLocation":"%s","PythonVersion":"3"},"GlueVersion":"%s","WorkerType":"%s","NumberOfWorkers":%s,"Timeout":%s,"DefaultArguments":%s}' \
          "$ROLE_ARN" "$SCRIPTS_S3/$script.py" "$GLUE_VERSION" "$WORKER_TYPE" "$workers" "$TIMEOUT_MIN" "$args")
    aws glue update-job --job-name "$nome" --job-update "$upd" >/dev/null
    echo "  atualizado: $nome"
  else
    aws glue create-job --name "$nome" "${comum[@]}" >/dev/null
    echo "  criado: $nome"
  fi
}

B2S=$(printf '{"--BRONZE_BUCKET":"%s","--SILVER_BUCKET":"%s","--job-language":"python"}' "$BRONZE_BUCKET" "$SILVER_BUCKET")
S2G=$(printf '{"--SILVER_BUCKET":"%s","--GOLD_BUCKET":"%s","--job-language":"python"}' "$SILVER_BUCKET" "$GOLD_BUCKET")

echo "== Jobs novos"
criar_ou_atualizar "$JOB_DESTINOS_SILVER" glue_destinos_bronze_para_silver "$WORKERS_ANAC" "$B2S"
criar_ou_atualizar "$JOB_TRENDS_SILVER"   glue_trends_bronze_para_silver   "$WORKERS_PEQUENO" "$B2S"
criar_ou_atualizar "$JOB_GOLD"            glue_silver_para_gold            "$WORKERS_PEQUENO" "$S2G"
criar_ou_atualizar "$JOB_DESTINOS_GOLD"   glue_destinos_silver_para_gold   "$WORKERS_PEQUENO" "$S2G"

echo
echo "Pronto. Para rodar: bash aws/executar_pipeline.sh"
