-- Tabelas do Athena sobre o bucket gold, lidas pelo dashboard do Grafana.
-- Troque <GOLD_BUCKET> pelo nome do bucket gold e rode um comando por vez no
-- editor do Athena. Os arquivos sao os gravados por scripts/glue_silver_para_gold.py:
-- UTF-8, separador ';', cabecalho na primeira linha. Campo vazio em coluna
-- numerica vira NULL (semana sem dado no Trends, por exemplo).

CREATE DATABASE IF NOT EXISTS grupo4_gold;

CREATE EXTERNAL TABLE IF NOT EXISTS grupo4_gold.cruzamento_semanal_br (
  semana_inicio                 date,
  semana_fim                    date,
  ano_semana                    int,
  num_semana                    int,
  mes_referencia                int,
  estacao                       string,
  temporada                     string,
  dias_cobertos                 int,
  semana_completa               boolean,
  evento                        string,
  qtd_voos                      int,
  nr_passageiros                bigint,
  pax_por_voo                   double,
  pax_indice                    double,
  voos_eua                      int,
  voos_canada                   int,
  voos_reino_unido              int,
  pax_eua                       bigint,
  pax_canada                    bigint,
  pax_reino_unido               bigint,
  tr_intencao_ingles            double,
  tr_curso_ingles               double,
  tr_aula_ingles                double,
  tr_aprender_ingles            double,
  tr_ingles_online              double,
  tr_professor_ingles           double,
  tr_intercambio                double,
  tr_visto_americano            double,
  tr_passagem_aerea             double,
  tr_curso_online               double,
  tr_razao_ingles_curso_online  double
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ';'
STORED AS TEXTFILE
LOCATION 's3://<GOLD_BUCKET>/cruzamento_semanal_br/'
TBLPROPERTIES ('skip.header.line.count' = '1');

CREATE EXTERNAL TABLE IF NOT EXISTS grupo4_gold.cruzamento_semanal_uf (
  semana_inicio       date,
  semana_fim          date,
  ano_semana          int,
  num_semana          int,
  mes_referencia      int,
  temporada           string,
  semana_completa     boolean,
  sg_uf               string,
  nome_uf             string,
  regiao              string,
  qtd_voos            int,
  nr_passageiros      bigint,
  tr_curso_ingles_uf  double,
  tem_dado_trends     boolean,
  cruzamento          string
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ';'
STORED AS TEXTFILE
LOCATION 's3://<GOLD_BUCKET>/cruzamento_semanal_uf/'
TBLPROPERTIES ('skip.header.line.count' = '1');

CREATE EXTERNAL TABLE IF NOT EXISTS grupo4_gold.resumo_uf (
  sg_uf                    string,
  nome_uf                  string,
  regiao                   string,
  qtd_voos                 int,
  nr_passageiros           bigint,
  pct_passageiros          double,
  interesse_curso_ingles   double,
  serie_semanal_trends     boolean,
  semanas_com_dado_trends  int,
  pearson_semanal          double,
  pares_semanal            int
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ';'
STORED AS TEXTFILE
LOCATION 's3://<GOLD_BUCKET>/resumo_uf/'
TBLPROPERTIES ('skip.header.line.count' = '1');

CREATE EXTERNAL TABLE IF NOT EXISTS grupo4_gold.correlacoes (
  recorte            string,
  serie_voos         string,
  serie_trends       string,
  transformacao      string,
  defasagem_semanas  int,
  pearson            double,
  spearman           double,
  n                  int,
  n_efetivo          double,
  r_critico_5pct     double,
  significativo      boolean
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ';'
STORED AS TEXTFILE
LOCATION 's3://<GOLD_BUCKET>/correlacoes/'
TBLPROPERTIES ('skip.header.line.count' = '1');

-- Grupo de comparacao (destinos nao anglofonos), gravado por
-- scripts/glue_destinos_silver_para_gold.py.

CREATE EXTERNAL TABLE IF NOT EXISTS grupo4_gold.comparacao_destinos_semanal (
  semana_inicio                 date,
  semana_fim                    date,
  ano_semana                    int,
  num_semana                    int,
  mes_referencia                int,
  estacao                       string,
  temporada                     string,
  dias_cobertos                 int,
  semana_completa               boolean,
  segmento                      string,
  segmento_nome                 string,
  qtd_voos                      int,
  nr_passageiros                bigint,
  pax_indice                    double,
  participacao_pax              double,
  tr_curso_ingles               double,
  tr_intencao_ingles            double,
  tr_aula_ingles                double,
  tr_curso_online               double,
  tr_razao_ingles_curso_online  double
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ';'
STORED AS TEXTFILE
LOCATION 's3://<GOLD_BUCKET>/comparacao_destinos_semanal/'
TBLPROPERTIES ('skip.header.line.count' = '1');

CREATE EXTERNAL TABLE IF NOT EXISTS grupo4_gold.correlacoes_destinos (
  segmento           string,
  serie_voos         string,
  serie_trends       string,
  transformacao      string,
  defasagem_semanas  int,
  pearson            double,
  spearman           double,
  n                  int,
  n_efetivo          double,
  r_critico_5pct     double,
  significativo      boolean
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ';'
STORED AS TEXTFILE
LOCATION 's3://<GOLD_BUCKET>/correlacoes_destinos/'
TBLPROPERTIES ('skip.header.line.count' = '1');

CREATE EXTERNAL TABLE IF NOT EXISTS grupo4_gold.parciais_destinos (
  serie_trends       string,
  explicativa        string,
  controle           string,
  defasagem_semanas  int,
  pearson_parcial    double,
  pearson_simples    double,
  n                  int,
  n_efetivo          double,
  r_critico_5pct     double,
  significativo      boolean
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ';'
STORED AS TEXTFILE
LOCATION 's3://<GOLD_BUCKET>/parciais_destinos/'
TBLPROPERTIES ('skip.header.line.count' = '1');
