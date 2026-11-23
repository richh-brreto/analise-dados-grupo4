# Dashboard do Grafana: voos × intenção de estudar inglês

Arquivos desta pasta:

| Arquivo | Para que serve |
|---|---|
| `athena_ddl.sql` | cria o banco `grupo4_gold` e as sete tabelas do Athena sobre o bucket gold (quatro do recorte, três do grupo de comparação) |
| `dashboard_voos_x_trends.json` | dashboard pronto para importar (gerado por `scripts/gerar_dashboard_grafana.py`) |

## 1. Tabelas no Athena

1. Rode o job `glue_silver_para_gold.py` (ou copie `data/gold/` para o bucket gold mantendo as pastas).
2. No editor do Athena, abra `athena_ddl.sql`, troque `<GOLD_BUCKET>` pelo nome do bucket e rode um comando por vez.
3. Confira: `SELECT COUNT(*) FROM grupo4_gold.cruzamento_semanal_br` deve devolver 83.

## 2. Fonte de dados no Grafana

1. Instale o plugin **Amazon Athena** (`grafana-athena-datasource`): em Administration, Plugins, procure por Athena.
2. Em Connections, Data sources, adicione uma fonte Athena com:
   - Authentication: chave de acesso de um usuário IAM com leitura no bucket gold, permissão de consulta no Athena e escrita no bucket de resultados do Athena (ou a role da instância, se o Grafana rodar numa EC2 do projeto);
   - Default Region: a região dos buckets;
   - Data source: `AwsDataCatalog`; Database: `grupo4_gold`; Workgroup: `primary`;
   - Output Location: um prefixo de um bucket de resultados (por exemplo `s3://<bucket-de-resultados>/athena/`).
3. Clique em Save & test.

## 3. Importação

Dashboards, New, Import, envie `dashboard_voos_x_trends.json` e escolha a fonte Athena criada no passo anterior. O intervalo de tempo já vem ajustado para o período dos dados (29/12/2024 a 01/08/2026).

As consultas foram escritas no subconjunto de SQL comum ao Athena (Trino) e ao DuckDB e testadas localmente com `python scripts/testar_consultas_grafana.py` (1.708 execuções, cobrindo todos os valores de todos os seletores, sem falha). O JSON segue o formato do Grafana 10.4, mas não foi importado num Grafana real durante o desenvolvimento: se algum painel abrir vazio, o primeiro lugar a olhar é o seletor de fonte de dados do painel.

## 4. Seletores do topo

| Seletor | Efeito |
|---|---|
| Termo do Trends | troca a série de busca no gráfico principal, no correlograma, na dispersão e no gráfico ano a ano |
| Série de voos | passageiros, voos, passageiros por voo ou passageiros por destino, no correlograma, na dispersão e nos números do topo |
| Transformação | nível (valores) ou variação semanal (mudança de uma semana para a outra, que tira tendência e sazonalidade comum) |
| Defasagem | k semanas entre voo e busca na dispersão e na matriz; positivo = a busca vem depois do voo |
| UF | UFs com voos e série semanal do Trends; repete o gráfico regional para cada uma |
| Termo (comparação de destinos) | série do Trends usada na linha Férias ou destino? (curso de inglês, intenção, aula de inglês, curso online ou a razão) |

Os eventos de calendário (Carnaval, Semana Santa, Natal, Ano-novo, Copa do Mundo de 2026) aparecem como anotações nas séries semanais.

## 5. Painéis

| Linha | Painel | Pergunta que responde |
|---|---|---|
| Resumo | passageiros, semanas, maior correlação, defasagem do pico | qual o tamanho da base e onde está o sinal mais forte para a combinação escolhida |
| Séries semanais | passageiros × termo (índice 0 a 100) | as duas séries sobem e descem juntas? Com quanto de atraso? |
| | termos de intenção | os cinco termos têm a mesma sazonalidade? (não: curso sobe nas férias, aula cai) |
| | contexto de viagem e controle | passagem aérea acompanha os voos; visto americano reage a notícia; curso online é o calendário educacional genérico |
| | passageiros por destino | quanto cada país pesa e se o pico é o mesmo nos três |
| | passageiros por voo | o pico vem de mais voos ou de voos mais cheios |
| Correlações | correlograma | correlação para cada defasagem de -8 a +8 semanas, destacando as significativas |
| | dispersão | o formato da relação na defasagem escolhida (linear? puxada por poucas semanas?) |
| | matriz de correlação | todas as séries de voos × todos os termos de uma vez |
| | ranking | os 30 pares mais correlacionados entre Brasil e UFs |
| Calendário | perfil por temporada | cada série nas férias, na volta às aulas e no período letivo |
| | ano a ano | 2025 sobreposto a 2026 por semana do ano |
| Regional | passageiros × busca por UF | a relação nacional se repete em SP, RJ e MG? |
| | correlograma por UF | idem, por defasagem |
| | interesse por UF e resumo | onde a busca relativa é maior e quanto cada UF embarca |
| Férias ou destino? | passageiros por destino × busca | anglófonos, não anglófonos, América do Sul e Europa na mesma base que a busca |
| | correlograma por destino | se só o destino importasse, os não anglófonos não teriam correlação |
| | correlação parcial | o que cada grupo explica além do outro |
| | composição | a fatia anglófona dos viajantes prevê a busca? (não) |
| | pico por destino | defasagem e força da maior correlação de cada segmento |

As conclusões tiradas destes painéis estão em `ANALISE_FINAL.md`, na raiz do repositório.

## 6. Versão local, sem AWS (plugin DuckDB)

Para explorar o dashboard enquanto a gold não está no S3. A pasta `grafana/local/` sobe um Grafana em Docker com o plugin DuckDB (`motherduck-duckdb-datasource`), que lê os CSVs de `data/gold` direto. Painéis, seletores e consultas são os mesmos do dashboard do Athena; o gerador produz as duas versões e o teste roda as duas.

Requisitos: Docker (no Windows, Docker Desktop) e a gold local gerada (`data/gold/`).

```bash
bash grafana/local/instalar_plugin.sh          # uma vez: baixa o plugin para grafana/local/plugins/
cd grafana/local && docker compose up -d
```

Abra `http://localhost:3000`: o dashboard abre direto, sem login (acesso anônimo como administrador, só para uso local). Depois de rodar o pipeline de novo, basta recarregar a página: as views leem os CSVs a cada consulta. Para parar: `docker compose down`.

Diferenças em relação à versão do Athena:

| | Athena | Local |
|---|---|---|
| Fonte | tabelas `grupo4_gold` no Athena | views do DuckDB sobre `data/gold/*/*.csv` |
| Seletor de tempo | filtra as consultas | não filtra (mostra sempre o período inteiro; dá para dar zoom nos gráficos) |
| Seletor de UF | lido da tabela | fixo em SP, RJ e MG |

O que a apresentação mostra deve sair da versão do Athena, que é a que roda sobre o pipeline na AWS. A local serve para explorar e ensaiar.
