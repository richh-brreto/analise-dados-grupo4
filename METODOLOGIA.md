# Metodologia de tratamento dos dados

Documentação do pipeline que transforma os arquivos brutos da ANAC em um CSV agregado de voos comerciais de passageiros partindo do Brasil com destino a países de língua inglesa e, na versão final, cruza esses voos semana a semana com o interesse de busca por aulas de inglês no Google Trends.

| Seções | Etapa |
|---|---|
| 1 a 8 | base da ANAC: limpeza, filtro, agregação mensal e gráficos da EDA |
| 9 | voos por semana e por aeroporto de embarque (UF e município) |
| 10 | coleta do Google Trends (bronze) e tratamento (silver) |
| 11 | cruzamento das duas bases (gold) |
| 12 | método estatístico das correlações |
| 13 | dashboard do Grafana |
| 14 | como reproduzir o pipeline completo, local e na AWS |
| 15 | grupo de comparação: voos para destinos não anglófonos (férias ou destino?) |

As hipóteses e conclusões da análise estão em `ANALISE_FINAL.md`.

## 1. Dados de origem

Os dados brutos ficam em `data/`, organizados em uma pasta por mês:

```
data/
  combinada2025-01/
    combinada2025-01.zip   (arquivo original compactado, não utilizado)
    combinada2025-01.txt   (dado bruto, utilizado)
    combinada2025-01.csv   (gerado pela limpeza)
  combinada2025-02/
  ...
  combinada2026-07/
```

Características dos arquivos `.txt`:

| Propriedade | Valor |
|---|---|
| Período coberto | 2025-01 a 2026-07 (19 arquivos) |
| Volume | cerca de 150 MB a 170 MB por arquivo, 2,9 GB no total |
| Registros | 3.709.917 linhas somando todos os meses |
| Codificação | ISO 8859-1 (Latin-1) |
| Delimitador | ponto e vírgula (`;`) |
| Aspas | aspas duplas em todos os campos de texto |
| Quebra de linha | CRLF |
| Colunas | 90, com cabeçalho idêntico em todos os 19 arquivos (verificado por checksum) |

Os arquivos `.zip` não entram no pipeline. São apenas a versão compactada do mesmo conteúdo dos `.txt`.

## 2. Formatação adotada na saída

Todos os CSVs gerados seguem o mesmo padrão:

| Propriedade | Valor | Motivo |
|---|---|---|
| Codificação | ISO 8859-1 (Latin-1) | mesma da origem, preserva acentuação (`IBÉRIA`, `ESPAÑA`, `CANADÁ`) sem conversão |
| Delimitador | ponto e vírgula (`;`) | mantido igual ao original |
| Aspas | mínimas (`QUOTE_MINIMAL`) | só aplicadas quando o campo contém `;`, aspas ou quebra de linha |
| Nomes de coluna | snake_case minúsculo | padronização programática |

Atenção ao ler os arquivos: o console do Windows exibe caracteres acentuados de forma corrompida (`IB?RIA`) mesmo quando o arquivo está correto. A verificação confiável é abrir o arquivo declarando `encoding='latin-1'`, nunca confiar na exibição do terminal.

## 3. Limpeza e padronização

Script: `scripts/clean_combinada.py`

Entrada: os 19 arquivos `data/combinadaYYYY-MM/combinadaYYYY-MM.txt`
Saída: um `data/combinadaYYYY-MM/combinadaYYYY-MM.csv` por mês

### 3.1 Estratégia de duas passadas

O volume total (2,9 GB) inviabiliza carregar tudo em memória, então o processamento é feito por streaming, em duas passadas sobre os arquivos:

1. **Primeira passada:** percorre todas as linhas de todos os meses marcando, para cada uma das 90 colunas, se existe ao menos um valor não vazio. O resultado é uma máscara global de colunas.
2. **Segunda passada:** relê os arquivos e grava os CSVs contendo apenas as colunas aprovadas na máscara.

A análise de colunas vazias foi feita sobre o conjunto completo dos 19 meses, e não arquivo por arquivo. Isso garante que todos os CSVs de saída tenham exatamente o mesmo conjunto de colunas, o que é pré-requisito para a etapa de agregação.

### 3.2 Resultado da remoção de colunas vazias

**Nenhuma coluna foi removida.** As 90 colunas originais têm ao menos um valor preenchido em algum registro do período. Colunas que parecem vazias em um recorte específico, como `sg_uf_origem` em voos internacionais, aparecem preenchidas em voos domésticos.

### 3.3 Padronização dos nomes de coluna

Cada nome passa por: remoção de espaços nas bordas, remoção de aspas residuais, conversão para minúsculo, substituição de caracteres não alfanuméricos por sublinhado e colapso de sublinhados repetidos.

Os nomes originais da ANAC já seguiam esse padrão, então o resultado é idêntico ao de entrada. A diferença é que agora a conformidade é garantida por código e não por inspeção manual.

## 4. Filtro e agregação

Script: `scripts/filter_ingles.py`

Entrada: os 19 CSVs limpos gerados na etapa anterior
Saída: `data/voos_brasil_paises_ingleses.csv`

### 4.1 Filtro geográfico

São mantidos apenas os registros que satisfazem as duas condições:

- `nm_pais_origem` igual a `BRASIL`
- `nm_pais_destino` em `{ESTADOS UNIDOS DA AMÉRICA, CANADÁ, REINO UNIDO}`

As grafias foram levantadas a partir dos valores distintos presentes no próprio dataset. Dois pontos importantes:

- O dataset escreve `ESTADOS UNIDOS DA AMÉRICA` por extenso, nunca `EUA`.
- Inglaterra não existe como valor. O país aparece como `REINO UNIDO`.

Irlanda, Austrália e Nova Zelândia não aparecem como destino de voos saídos do Brasil no período. A África do Sul (1.396 registros) e os demais países anglófonos presentes na base, todos com menos de 15 registros (Jamaica, Guiana, Trinidad e Tobago, Santa Lúcia, Barbados, Bahamas, Antígua e Barbuda, Nigéria, Quênia, Gana, Libéria, Malta e Singapura), foram deixados de fora por decisão de escopo, restringindo a análise aos três grandes destinos. Países de conexão com muito volume, como Portugal, Espanha, Chile e Qatar, não entram porque o destino do registro não é anglófono.

Resultado do filtro: 36.412 registros, a partir de 3.709.917 lidos.

### 4.2 Unidade de análise: de registro para voo

Na etapa combinada da ANAC, cada registro é um **par de aeroportos** (embarque × desembarque) dentro de um voo, e não um voo. Um voo que sai de São Paulo, faz escala em Miami e segue para Nova York gera dois registros com origem Brasil e destino Estados Unidos. Contar registros infla a quantidade de voos e, pior, classifica cada trecho isoladamente: o par que segue até o segundo destino pode ter poucos passageiros embarcados e parecer um voo pequeno, quando é um avião de linha.

Por isso os registros filtrados são primeiro somados ao voo a que pertencem, identificado pela chave `(sg_empresa_icao, nr_voo, dt_partida_real)`. O campo `nr_singular` fica fora da chave porque costuma vir vazio. Só depois cada voo entra, uma única vez, na agregação mensal.

| Registros por voo | Voos |
|---|---|
| 1 | 13.571 |
| 2 | 1.368 |
| 3 | 5.873 |
| 4 a 9 | 415 |

Os 36.412 registros correspondem a **21.227 voos distintos**. A contagem por registro superestimava o número de voos em 72%. A soma de passageiros não é afetada, porque cada registro traz apenas os embarques daquele trecho.

Nenhum voo toca mais de um dos três países de destino: somando os voos por país (Estados Unidos 15.656, Reino Unido 1.633, Canadá 1.038, considerando só os comerciais da seção 4.4) chega-se exatamente ao total.

### 4.3 Chave temporal

A agregação usa `nr_ano_mes_partida_real`, o mês da partida efetiva, e não `nr_ano_mes_referencia`, o mês de referência do arquivo da ANAC.

Consequência conhecida: aparecem 20 meses no resultado, e não 19. Dois voos do arquivo de julho de 2026 decolaram já em 1º de agosto e formam a linha residual de `2026-08` (2 voos, 617 passageiros). Para eliminar esse resíduo basta trocar a chave para o mês de referência.

### 4.4 Classificação do tipo de voo e exclusão dos cargueiros

Cada voo é classificado a partir de duas informações: o tipo de serviço da linha (`ds_servico_tipo_linha`, que assume os valores `PASSAGEIRO`, `CARGUEIRO` e `NÃO IDENTIFICADO`) e o total de passageiros embarcados no voo inteiro (`nr_passag_pagos` mais `nr_passag_gratis`, somados em todos os trechos).

| Categoria | Regra | Voos | Passageiros |
|---|---|---|---|
| `voo de carga/reabastecimento` | serviço `CARGUEIRO` ou nenhum passageiro a bordo | 2.900 | 0 |
| `voo comercial` | demais voos (linha de passageiros com ao menos um embarque) | 18.327 | 4.568.452 |

**Somente os voos comerciais entram no arquivo final.** Os de carga são apenas contados no resumo do console do script, porque não interessam para a análise de demanda por aulas de inglês. Como restou uma única categoria, o CSV não tem coluna de tipo.

A categoria de carga reúne 738 voos de serviço `CARGUEIRO`, 2.132 voos `NÃO IDENTIFICADO` sem passageiros e 30 voos `PASSAGEIRO` sem passageiros (posicionamento ou ferry). No período, nenhum voo `CARGUEIRO` registrou passageiro, então o critério de serviço é uma salvaguarda: a regra de zero passageiros já capturaria todos.

Uma versão anterior desta análise classificava por registro, e não por voo, e tinha uma terceira categoria, `voo privado`, para voos de 1 a 19 passageiros. Depois de agregar por voo, sobraram apenas 9 voos nessa faixa em 19 meses, todos de companhias aéreas comerciais (Delta, Azul, Air Transat e American), com 97 passageiros no total. A categoria era um artefato dos trechos de escala com poucos embarques e foi removida; esses 9 voos contam como comerciais.

### 4.5 Enriquecimento de calendário

Duas colunas derivadas do mês adicionam contexto sazonal. Como os voos partem do Brasil, o calendário aplicado é o brasileiro, do hemisfério sul. Nos destinos as estações são invertidas.

`estacao`, estações meteorológicas em blocos de trimestre:

| Meses | Valor |
|---|---|
| dezembro, janeiro, fevereiro | `verão` |
| março, abril, maio | `outono` |
| junho, julho, agosto | `inverno` |
| setembro, outubro, novembro | `primavera` |

`temporada`, calendário escolar brasileiro:

| Meses | Valor |
|---|---|
| janeiro, julho, dezembro | `férias escolares` |
| fevereiro, agosto | `volta às aulas` |
| demais meses | `período letivo` |

A coluna `temporada` separa a demanda com mais nitidez que `estacao`, porque julho é inverno mas é pico de férias. Nos meses completos (sem o resíduo de `2026-08`), férias escolares somam em média 269.295 passageiros por mês, contra 229.373 na volta às aulas e 230.295 no período letivo.

### 4.6 Granularidade e métricas

Cada linha do CSV final representa uma combinação de ano e mês. Dentro de cada grupo são calculados:

- `qtd_voos`: contagem de voos comerciais distintos (chave da seção 4.2)
- `nr_passageiros`: soma de `nr_passag_pagos` mais `nr_passag_gratis`

Os passageiros grátis, que incluem tripulação e funcionários em deslocamento, foram somados junto aos pagantes por decisão de escopo.

Resultado: 20 linhas, correspondendo aos 19 meses completos mais o mês residual.

## 5. Arquivo final

`data/voos_brasil_paises_ingleses.csv`

| Coluna | Tipo | Descrição |
|---|---|---|
| `ano` | inteiro | ano da partida real |
| `mes` | inteiro | mês da partida real, de 1 a 12 |
| `estacao` | texto | estação do ano no Brasil |
| `temporada` | texto | momento do calendário escolar brasileiro |
| `qtd_voos` | inteiro | total de voos comerciais no mês |
| `nr_passageiros` | inteiro | total de passageiros no mês |

Totais de controle: 20 linhas, 18.327 voos e 4.568.452 passageiros.

## 6. Como ler o arquivo

O ponto crítico é declarar a codificação e o separador. Sem isso os acentos quebram e tudo cai em uma coluna só.

Com pandas:

```python
import pandas as pd

df = pd.read_csv(
    "data/voos_brasil_paises_ingleses.csv",
    sep=";",
    encoding="latin-1",
)
```

Com a biblioteca padrão:

```python
import csv

with open("data/voos_brasil_paises_ingleses.csv", encoding="latin-1", newline="") as f:
    leitor = csv.DictReader(f, delimiter=";")
    for linha in leitor:
        print(linha["ano"], linha["mes"], linha["qtd_voos"], linha["nr_passageiros"])
```

No Excel em português, o arquivo abre corretamente com duplo clique, pois Latin-1 e ponto e vírgula são os padrões esperados pela versão brasileira. Em outras configurações regionais, use Dados, Obter Dados, De Texto/CSV e selecione origem Europeu Ocidental (ISO) e delimitador ponto e vírgula.

Os mesmos parâmetros valem para os 19 CSVs mensais limpos, que preservam as 90 colunas originais e servem para qualquer recorte diferente do adotado aqui.

## 7. Gráficos

Script: `scripts/graficos_comercial.py`

Entrada: `data/voos_brasil_paises_ingleses.csv`
Saída: quatro PNGs em `graficos/`

| Arquivo | Conteúdo |
|---|---|
| `01_comercial_mensal.png` | voos e passageiros por mês, com os meses de férias escolares destacados |
| `02_sazonalidade_ano_a_ano.png` | passageiros por mês do ano, uma linha por ano (2025 × 2026) |
| `03_sazonalidade_calendario.png` | média mensal de voos e passageiros por temporada escolar e por estação |
| `04_passageiros_por_voo.png` | média de passageiros por voo, mês a mês |

O mês residual `2026-08` (seção 4.3) é ignorado, pois não representa um mês completo e distorceria as séries e as médias. Sobram 19 meses, com 18.325 voos e 4.567.835 passageiros, média de 249 passageiros por voo. O pico é janeiro de 2026 (296.851 passageiros) e o vale, setembro de 2025 (213.411).

As médias por temporada e por estação são calculadas por mês (total do grupo dividido pelo número de meses), já que as categorias cobrem quantidades diferentes de meses. A série usa uma única cor; os anos, no gráfico ano a ano, usam uma rampa de um só matiz, verificada para daltonismo.

Este é o único script com dependência externa: `matplotlib`.

## 8. Como reproduzir

Ordem de execução, a partir da raiz do projeto:

```bash
python scripts/clean_combinada.py
```

```bash
python scripts/filter_ingles.py
```

```bash
python scripts/graficos_comercial.py
```

A primeira etapa lê os `.txt` e é a mais demorada, na casa de dezenas de minutos, por processar 2,9 GB em duas passadas. A segunda lê os CSVs limpos e roda em poucos minutos.

A limpeza e o filtro usam apenas a biblioteca padrão do Python. A etapa de gráficos precisa de `matplotlib` (`pip install matplotlib`) e roda em segundos.

Parâmetros ajustáveis, todos no topo de `scripts/filter_ingles.py`:

| Constante | Função |
|---|---|
| `PAISES_DESTINO_INGLES` | conjunto de países de destino considerados |
| `VOO_COLS` | colunas que identificam um voo (empresa, número e data de partida) |
| `SERVICO_CARGUEIRO` | valor de `ds_servico_tipo_linha` que marca voo cargueiro |
| `MES_COL` | campo usado como chave temporal |
| `ESTACAO_POR_MES` | mapa de mês para estação |
| `TEMPORADA_POR_MES` | mapa de mês para temporada escolar |

Em `scripts/graficos_comercial.py`, `MESES_EXCLUIDOS` lista os meses incompletos que ficam fora das séries.

## 9. Voos por semana e por aeroporto de embarque

Scripts: `scripts/glue_bronze_para_silver.py` (AWS Glue, a partir dos arquivos brutos no bucket bronze) e `scripts/voos_semanal.py` (local, a partir de `data/base_eda_ingles.csv`). Os dois aplicam as mesmas regras das seções 4.1 a 4.4 e gravam arquivos idênticos: o teste feito com partes simuladas do bronze reproduziu byte a byte as saídas semanais locais e os mesmos valores da base mensal da seção 5.

### 9.1 A semana

A semana vai de **domingo a sábado**, porque é assim que o Google Trends entrega o dado semanal: o cruzamento usa `semana_inicio` (o domingo) como chave. Cada voo cai na semana da sua data de partida real.

| Coluna | Regra |
|---|---|
| `semana_inicio` | domingo da semana da partida |
| `semana_fim` | sábado seguinte |
| `ano_semana`, `num_semana` | ano e número pela quarta-feira da semana, a regra da semana epidemiológica brasileira (a semana pertence ao ano que tem a maior parte dos seus dias) |
| `mes_referencia` | mês da quarta-feira; define `estacao` e `temporada` quando a semana cruza dois meses |
| `dias_cobertos` | quantos dos 7 dias estão em meses cobertos pela base |
| `semana_completa` | `dias_cobertos = 7` |

Um mês só conta como coberto se tiver pelo menos metade da mediana mensal de voos, o que isola o resíduo de agosto/2026 (seção 4.3) sem precisar de data fixa no código. Resultado: **83 semanas**, de 29/12/2024 a 26/07/2026, das quais **81 completas**. A primeira semana tem 4 dias cobertos (1º a 4/1/2025) e a última tem 6 (o sábado 01/08/2026 está num arquivo que não foi baixado). As duas ficam fora das correlações.

### 9.2 Recorte regional

A ANAC informa UF e município do **aeroporto de embarque** (`sg_uf_origem`, `nm_municipio_origem`), não a residência do passageiro. Guarulhos concentra conexões do país inteiro, então a participação de SP mede o hub, não a demanda paulista.

Nos voos comerciais do recorte só **8 UFs** têm embarque: SP (76,3% dos passageiros), RJ (13,4%), DF (5,2%), MG (2,0%), CE, PA, PE e AM. PR, SC, ES, RS e RR aparecem na base só com cargueiros.

### 9.3 Duas tabelas, duas regras de contagem

| Tabela (silver) | Grão | Contagem de voos |
|---|---|---|
| `voos_semanal` | semana x país de destino | cada voo uma vez; soma 18.327 voos e 4.568.452 passageiros, igual à base mensal |
| `voos_semanal_uf` | semana x UF x município x país de destino | voo com embarque em dois aeroportos conta em cada um (19 voos); passageiros são os embarcados naquele aeroporto e somam exatamente o total nacional |

O Brasil inteiro usa sempre `voos_semanal`, para não contar duas vezes os 19 voos com dois embarques. Linhas com `nr_passageiros = 0` em `voos_semanal_uf` são escalas em que ninguém embarcou num voo que levava passageiros de outro aeroporto.

## 10. Google Trends

### 10.1 O que o índice mede

O Trends não dá volume de buscas. Para cada semana ele dá a participação das buscas do termo no total de buscas da região, reescalada para que o maior ponto da requisição valha 100. Três consequências guiaram o tratamento:

1. valores só são comparáveis dentro da mesma requisição;
2. termos pedidos juntos (até 5) saem na mesma escala, e por isso podem ser comparados e somados;
3. regiões pequenas ficam sem dado nas semanas em que o volume não atinge o limiar de privacidade do Google (`hasData = false`), o que é diferente de zero busca.

### 10.2 Termos

| Grupo | Termos | Papel |
|---|---|---|
| `intencao_ingles` | curso de inglês, aula de inglês, aprender inglês, inglês online, professor de inglês | intenção de estudar; o léxico segue a conversa de agosto com o grupo: termos de produto online e de aula particular, evitando "escola de inglês" e "perto de mim", que carregam intenção presencial |
| `contexto_viagem` | curso de inglês (âncora), intercâmbio, visto americano, passagem aérea, curso online | intenção de viajar e o **controle**: "curso online" carrega o calendário educacional genérico (ano-novo, volta às aulas); se o inglês tem a mesma forma que ele, o que se achou é o calendário, não o inglês |
| `uf_curso_ingles` | curso de inglês em SP, RJ, MG, DF e PR | mesmo termo, cinco UFs na mesma escala |
| `mapa_uf` | curso de inglês, Brasil por UF | interesse relativo das 27 UFs no período inteiro |

As UFs da série semanal são as que têm voo comercial e volume de busca. Os testes mostraram dado semanal completo só em SP, RJ e MG; DF tem dado em 17 de 83 semanas e PR em 56 (e PR não tem voo comercial no recorte). UFs menores (CE, PE, PA, AM) ficariam praticamente sem dado semanal, e o Trends não tem série semanal utilizável por cidade. Por isso o recorte regional dos dois lados termina na UF.

### 10.3 Coleta (bronze)

Script: `scripts/coletar_google_trends.py`. Faz as mesmas chamadas que a página Explorar do Trends faz no navegador (`/trends/api/explore`, depois `widgetdata/multiline` e `widgetdata/comparedgeo`), com espera aleatória de 20 a 40 segundos entre chamadas e nova tentativa com espera crescente quando o Google responde 429. Não usa o `pytrends`, que está arquivado e faz as mesmas chamadas; a API oficial do Trends segue em alpha com acesso restrito.

Períodos de até cerca de 5 anos (1.800 dias) vão numa requisição só, que já volta em dado semanal e dispensa emenda. Períodos maiores, ou a opção `--janela-dias`, são divididos em janelas de 300 dias sobrepostas em 3 semanas; janelas acima de 270 dias garantem dado semanal, e a sobreposição permite emendá-las. A primeira coleta desta análise (jan/2025 a jul/2026) foi feita em duas janelas, 2024-12-29 a 2025-10-25 e 2025-10-05 a 2026-08-01.

Arquivos gravados, um por requisição, UTF-8 e separador `;`, todos bem abaixo de 600 KB (cabem na Lambda sem divisão):

```
data/bronze/google_trends/series/<grupo>/<grupo>_<inicio>_<fim>.csv
data/bronze/google_trends/mapa_uf/mapa_uf_<inicio>_<fim>.csv
```

Colunas da série: `grupo, termo, geo, janela_inicio, janela_fim, semana_inicio, valor, tem_dado, parcial, coletado_em`.

**Sobre a coleta desta versão (22/11/2026).** O ambiente em que o pipeline foi montado não alcança o Google Trends pela rede, então os arquivos bronze versionados foram gerados a partir das respostas dessas mesmas chamadas, abertas no navegador, e gravados no formato exato do coletor. Cada resposta do Trends traz a média de cada série na janela; a média recalculada dos valores gravados confere com ela em todas as 30 séries (diferença máxima de 0,56 ponto, explicada pelo arredondamento dos valores semanais). Rodar o coletor de uma rede comum reproduz a coleta; pequenas diferenças entre coletas são esperadas, porque o Trends trabalha com amostra.

### 10.4 Tratamento (silver)

Script: `scripts/glue_trends_bronze_para_silver.py`. Lê o bronze de forma recursiva (partes geradas pelo `chunk_arquivos.py` também servem) e grava três tabelas.

1. **Coleta repetida.** Se a mesma janela de um grupo foi coletada mais de uma vez, fica a mais recente.
2. **Sem dado vira nulo.** `tem_dado = false` vira valor vazio, nunca zero.
3. **Emenda entre janelas.** A janela seguinte é multiplicada pelo fator que iguala a soma das semanas repetidas nas duas janelas, calculado com todos os termos do grupo juntos (assim a proporção entre termos não muda). Nas semanas repetidas fica a média das duas janelas.
4. **Escala final.** Cada grupo é reescalado para 100 no seu maior valor no período inteiro. Termos do mesmo grupo continuam comparáveis; grupos diferentes, não.

| Tabela (silver) | Grão | Linhas |
|---|---|---|
| `google_trends_semanal` | grupo x termo x geo x semana | 1.245 |
| `google_trends_mapa_uf` | UF | 27 |
| `google_trends_emenda` | grupo x par de janelas | 3 |

A tabela de emenda é o controle de qualidade: nas semanas repetidas, a janela reescalada difere da anterior em média 0,87% (intenção), 0,81% (contexto) e 1,09% (UFs). A emenda não introduz degrau perceptível.

## 11. Cruzamento (gold)

Script: `scripts/glue_silver_para_gold.py`. Junta `voos_semanal`, `voos_semanal_uf`, `google_trends_semanal` e `google_trends_mapa_uf` pela **semana** (`semana_inicio`) e, no recorte regional, pela **UF**.

| Tabela (gold) | Grão | Linhas | Conteúdo |
|---|---|---|---|
| `cruzamento_semanal_br` | semana | 83 | voos e passageiros (total e por país), ocupação, índice de passageiros e as 11 séries nacionais do Trends, mais eventos de calendário |
| `cruzamento_semanal_uf` | semana x UF | 747 | voos e passageiros embarcados na UF e busca por curso de inglês na UF |
| `resumo_uf` | UF | 27 | totais de voos, participação, interesse relativo no Trends e correlação semanal |
| `correlacoes` | recorte x par de séries x transformação x defasagem | 2.448 | Pearson, Spearman, n, n efetivo e significância |

Colunas derivadas na gold:

| Coluna | Fórmula |
|---|---|
| `pax_indice` | passageiros / maior semana completa x 100; põe voos e Trends na mesma base sem eixo duplo |
| `pax_por_voo` | passageiros / voos |
| `tr_intencao_ingles` | soma dos 5 termos de intenção (mesma escala), maior semana = 100 |
| `tr_razao_ingles_curso_online` | curso de inglês / curso online x 100, os dois da mesma requisição; isola o interesse específico por inglês |
| `evento` | Ano-novo, Carnaval, Semana Santa, Natal e Copa do Mundo de 2026 (11/06 a 19/07/2026, nos EUA, Canadá e México), na semana em que caem |

**Granularidade regional identificada.** O cruzamento regional semanal com os dois lados completos é possível em **SP, RJ e MG**. DF tem voos mas só 17 semanas com dado no Trends (fica na tabela, fora das correlações, que exigem 20 pares). AM, CE, PA e PE têm voos e não têm série semanal no Trends; PR tem série no Trends e nenhum voo comercial no recorte. A coluna `cruzamento` de `cruzamento_semanal_uf` marca cada caso. No nível de município só o lado dos voos existe.

## 12. Método estatístico

**Defasagem.** Para cada par de séries, a correlação é calculada entre voos na semana t e busca na semana t+k, para k de -8 a +8. k positivo: a busca acontece depois do voo; k negativo: antes.

**Transformações.** Em `nivel` comparam-se os valores. Em `variacao` comparam-se as diferenças de uma semana para a seguinte, o que remove tendência e sazonalidade comum e pergunta se os choques semanais andam juntos.

**Significância.** Semanas vizinhas não são observações independentes: quase todas as séries têm autocorrelação de lag 1 entre 0,6 e 0,9 (a exceção são os passageiros para o Reino Unido, 0,12). Tratar as 81 semanas como 81 observações exageraria a significância. Usa-se o tamanho efetivo da amostra de Bretherton et al. (1999):

```
n_efetivo = n x (1 - r1x x r1y) / (1 + r1x x r1y)
r_critico_5pct = 1,96 / raiz(n_efetivo - 2)
```

onde r1x e r1y são as autocorrelações de lag 1 das duas séries. Nas correlações de nível do Brasil o n efetivo tem mediana 23 (metade entre 19 e 32), não 81. O script de análise (`scripts/analise_hipoteses.py`) usa o mesmo n efetivo para o p-valor pela distribuição t.

**Testes adicionais** (`scripts/analise_hipoteses.py`, resultados em `graficos/cruzamento/resultados.json`): correlação parcial controlando pelo termo "curso online"; correlação sem dezembro e janeiro; comparação junho x julho; ano contra ano na mesma semana; perfil por temporada; teste de precedência de Granger nas variações semanais do logaritmo, até 4 semanas.

## 13. Dashboard do Grafana

Pasta `grafana/`: DDL do Athena sobre o bucket gold, JSON de importação do dashboard e instruções (`grafana/README.md`). O JSON é gerado por `scripts/gerar_dashboard_grafana.py` e todas as consultas são testadas por `scripts/testar_consultas_grafana.py`, que roda cada uma no DuckDB contra `data/gold` em todas as combinações dos seletores (1.708 execuções).

Os gráficos estáticos equivalentes, usados no relatório, ficam em `graficos/cruzamento/`. Para explorar sem AWS, `grafana/local/` tem uma versão do mesmo dashboard que lê os CSVs de `data/gold` por um plugin DuckDB, num Grafana em Docker (`grafana/README.md`, seção 6).

## 14. Como reproduzir o pipeline completo

A pasta `data/` espelha os buckets: `data/bronze`, `data/silver` e `data/gold` têm os mesmos caminhos relativos que as chaves dos buckets.

### 14.1 Local

O jeito mais simples é o script `rodar_pipeline_local.sh`, na raiz, que faz tudo em sequência: descompacta os meses da ANAC que estiverem em `.zip`, roda `clean_combinada.py` e `filter_eda.py` no workspace analise-pi (pasta indicada por `ANALISE_PI`, padrão `../analise-pi`), gera a silver de voos a partir de `base_eda_internacional.csv`, coleta o Trends para o mesmo período dos voos, roda os três jobs do Glue em modo local, as duas análises, o dashboard com o teste das consultas e o PDF dos gráficos. Opções `--sem-anac` e `--sem-trends` pulam essas etapas. A coleta nova só substitui o bronze do Trends depois de terminar sem erro; a anterior fica guardada em `data/bronze_arquivo/`. Os logs dos jobs do Spark ficam em `logs/`.

```bash
bash rodar_pipeline_local.sh
```

Passo a passo, se preferir rodar cada etapa:

```bash
pip install requests pyspark pandas numpy scipy statsmodels matplotlib duckdb
```

```bash
python scripts/voos_semanal.py                                                   # ANAC: silver semanal
python scripts/coletar_google_trends.py                                          # Trends: bronze
python scripts/glue_trends_bronze_para_silver.py --local data/bronze data/silver # Trends: silver
python scripts/glue_silver_para_gold.py --local data/silver data/gold            # cruzamento: gold
python scripts/analise_hipoteses.py                                              # testes e gráficos
python scripts/gerar_dashboard_grafana.py                                        # dashboard
python scripts/testar_consultas_grafana.py                                       # testa o SQL do dashboard
```

Grupo de comparação (seção 15), depois do Trends silver:

```bash
python scripts/voos_semanal_destinos.py ../analise-pi/data/base_eda_internacional.csv
python scripts/glue_destinos_silver_para_gold.py --local data/silver data/gold
python scripts/analise_destinos.py
```

Os jobs do Glue rodam localmente com `pyspark` (precisa de Java 17 ou mais novo). A coleta do Trends é a etapa lenta (cerca de 10 minutos, pela espera entre chamadas) e é opcional: os arquivos bronze desta versão estão versionados. `voos_semanal.py` substitui, localmente, o trecho semanal do `glue_bronze_para_silver.py`, já que os arquivos brutos não ficam no repositório. Ele aceita tanto `base_eda_ingles.csv` quanto `base_eda_internacional.csv` (filtrando `grupo_destino = RECORTE`); as duas dão arquivos idênticos.

Os scripts das seções 3 a 7 (`clean_combinada.py`, `filter_ingles.py`, `graficos_comercial.py`) não estão neste repositório; a base que eles geram (`data/base_eda_ingles.csv`) está.

### 14.2 AWS

A pasta `aws/` automatiza a implantação e a execução, com a AWS CLI:

| Arquivo | Função |
|---|---|
| `aws/config.sh` | região, buckets, role do Glue, nome do job que já existia e nomes dos jobs novos |
| `aws/implantar_glue.sh` | grava o script novo por cima do script do job existente (guardando cópia do antigo), sobe os scripts dos jobs novos e a coleta do Trends para o bronze, e cria ou atualiza os quatro jobs novos |
| `aws/executar_pipeline.sh` | roda as duas etapas na ordem, espera cada job terminar e compara silver e gold da AWS com `data/` |

Os cinco jobs foram executados localmente no runtime do Glue 5.0 (Spark 3.5.4, Python 3.11) e produziram arquivos idênticos aos de `data/`.


| Ordem | Job do Glue | Parâmetros | Lê | Grava |
|---|---|---|---|---|
| 1 | `glue_bronze_para_silver.py` | `--BRONZE_BUCKET`, `--SILVER_BUCKET` | `combinada*/` no bronze | `voos_brasil_paises_ingleses/`, `voos_semanal/`, `voos_semanal_uf/` |
| 2 | `glue_trends_bronze_para_silver.py` | `--BRONZE_BUCKET`, `--SILVER_BUCKET` | `google_trends/` no bronze | `google_trends_semanal/`, `google_trends_mapa_uf/`, `google_trends_emenda/` |
| 3 | `glue_silver_para_gold.py` | `--SILVER_BUCKET`, `--GOLD_BUCKET` | as tabelas silver acima | `cruzamento_semanal_br/`, `cruzamento_semanal_uf/`, `resumo_uf/`, `correlacoes/` |

| 4 | `glue_destinos_bronze_para_silver.py` | `--BRONZE_BUCKET`, `--SILVER_BUCKET` | `combinada*/` no bronze | `voos_semanal_destinos/` |
| 5 | `glue_destinos_silver_para_gold.py` | `--SILVER_BUCKET`, `--GOLD_BUCKET` | `voos_semanal_destinos/`, `google_trends_semanal/` | `comparacao_destinos_semanal/`, `correlacoes_destinos/`, `parciais_destinos/` |

Os jobs 1, 2 e 4 são independentes; o 3 depende de 1 e 2, e o 5 depende de 2 e 4. Os arquivos do Trends vão para o bronze pela Lambda com a chave `google_trends/series/<grupo>/<arquivo>.csv` e `google_trends/mapa_uf/<arquivo>.csv`. Depois do job 3, rode `grafana/athena_ddl.sql` uma vez no Athena e importe o dashboard (seção 13).

Para acrescentar meses: baixe os novos arquivos da ANAC para o bronze, rode o coletor do Trends com `--fim` no sábado da última semana (ele cria uma janela nova sobreposta à anterior) e rode os três jobs. A emenda e a escala são recalculadas sobre o período inteiro.

## 15. Grupo de comparação: destinos não anglófonos

A relação entre voos e busca (seção 12 e `ANALISE_FINAL.md`) podia ser efeito das férias, e não do destino de língua inglesa: os voos para a Argentina e o Chile também sobem nas férias. Para separar os dois, os voos para todos os outros destinos internacionais entram como grupo de comparação, em tabelas próprias, sem mexer nas do recorte do projeto.

### 15.1 Base e regras

Scripts: `scripts/glue_destinos_bronze_para_silver.py` (Glue, a partir dos arquivos brutos) e `scripts/voos_semanal_destinos.py` (local, a partir de `base_eda_internacional.csv`, a base da EDA gerada por `filter_eda.py` no workspace analise-pi, com todos os destinos). A base local não é versionada (52 MB); o script recebe o caminho como argumento. Os dois gravam o mesmo arquivo (conferido com partes simuladas do bronze).

Grupos de destino, os mesmos da EDA:

| Grupo | Países |
|---|---|
| `RECORTE` | Estados Unidos, Canadá, Reino Unido |
| `OUTRO ANGLÓFONO` | África do Sul e 19 países de língua oficial inglesa com pouco volume |
| `NÃO ANGLÓFONO` | todos os demais |

As regras de voo são as do recorte (seções 4.2 e 4.4), aplicadas dentro de cada grupo e continente de destino: um voo que pousa na Argentina e depois nos EUA conta nos dois grupos, cada um com os passageiros embarcados para o seu destino. As 6 linhas repetidas entre arquivos mensais (seção de qualidade da EDA), todas de destinos não anglófonos, entram uma vez só. A semana, a cobertura e o calendário seguem a seção 9.

Conferência: o grupo `RECORTE` reproduz exatamente `voos_semanal` (18.327 voos e 4.568.452 passageiros, semana a semana).

| Grupo | Voos | Passageiros |
|---|---|---|
| RECORTE | 18.327 | 4.568.452 |
| NÃO ANGLÓFONO | 101.727 (252 voos contados em dois continentes) | 18.755.104 |
| OUTRO ANGLÓFONO | 702 | 154.506 |

### 15.2 Tabelas

| Tabela | Camada | Grão | Linhas |
|---|---|---|---|
| `voos_semanal_destinos` | silver | semana x grupo de destino x continente | 755 |
| `comparacao_destinos_semanal` | gold | semana x segmento | 664 |
| `correlacoes_destinos` | gold | segmento x série de voos x série do Trends x transformação x defasagem | 2.210 |
| `parciais_destinos` | gold | série do Trends x grupo explicativo x controle x defasagem | 170 |

Segmentos da gold: `anglofono` (o recorte), `nao_anglofono` (todos), e o não anglófono aberto em `nao_anglofono_america_sul`, `nao_anglofono_europa`, `nao_anglofono_america_cn` (América Central e México) e `nao_anglofono_outros` (África, Ásia e Oceania); mais `outro_anglofono` e `internacional` (todos os destinos). Colunas derivadas: `pax_indice` (100 = maior semana completa do segmento) e `participacao_pax` (fatia do segmento nos passageiros internacionais da semana). As séries do Trends da semana vêm repetidas em cada linha para facilitar os gráficos.

### 15.3 Testes

1. **Correlação por segmento**, com as mesmas defasagens, transformações e significância da seção 12: se só o destino importasse, os não anglófonos não teriam correlação com a busca.
2. **Correlação parcial**: a correlação dos passageiros anglófonos (semana t) com a busca (t+k) depois de retirar, por regressão linear, o que os não anglófonos da mesma semana explicam; e o inverso.
3. **Composição**: a participação anglófona no total internacional contra a busca. Se o destino importasse, semanas com proporcionalmente mais viagem para países de língua inglesa seriam seguidas de mais busca.
4. **Variância explicada** (`scripts/analise_destinos.py`): R² da busca três semanas depois com só os anglófonos, só os não anglófonos e os dois.

Resultados e gráficos: `graficos/comparacao_destinos/` e `ANALISE_FINAL.md`, seção 4.
