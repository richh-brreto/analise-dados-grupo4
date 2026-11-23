# shellcheck shell=bash disable=SC2034
# Configuracao usada por implantar_glue.sh e executar_pipeline.sh.
# Preencha uma vez; os dois scripts leem daqui.

REGIAO="us-east-1"

BRONZE_BUCKET="bronze-layer-data-527907796503-us-east-1"
SILVER_BUCKET="silver-layer-data-527907796503-us-east-1"
GOLD_BUCKET="gold-layer-data-527907796503-us-east-1"

# Onde os scripts dos jobs ficam no S3 (qualquer bucket/prefixo que a role do Glue leia)
SCRIPTS_S3="s3://${BRONZE_BUCKET}/glue-scripts"

# Role que os jobs novos assumem. No AWS Academy costuma ser LabRole.
GLUE_ROLE="LabRole"

# Nome do job que ja existe hoje (bronze -> silver da ANAC). Ele NAO e recriado:
# o script novo e gravado por cima do arquivo para o qual o job ja aponta, e o
# resto da configuracao dele (role, workers, parametros) continua como esta.
JOB_ANAC_EXISTENTE="boost-anac-bronze-to-silver"

# Jobs novos
JOB_DESTINOS_SILVER="grupo4-destinos-bronze-para-silver"
JOB_TRENDS_SILVER="grupo4-trends-bronze-para-silver"
JOB_GOLD="grupo4-silver-para-gold"
JOB_DESTINOS_GOLD="grupo4-destinos-silver-para-gold"

GLUE_VERSION="5.0"        # 4.0 tambem funciona
WORKER_TYPE="G.1X"
WORKERS_ANAC=5            # le os 2,9 GB brutos da ANAC
WORKERS_PEQUENO=2         # Trends e gold leem poucos KB
TIMEOUT_MIN=60
