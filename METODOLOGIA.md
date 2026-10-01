# Metodologia de tratamento dos dados

Documentação do pipeline que transforma os arquivos brutos da ANAC em um CSV agregado de voos comerciais de passageiros partindo do Brasil com destino a países de língua inglesa.

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
