# Metodologia de tratamento dos dados

Documentação do pipeline que transforma os arquivos brutos da ANAC em um CSV agregado de voos partindo do Brasil com destino a países de língua inglesa.

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

Países anglófonos menores presentes nos dados (Jamaica, Barbados, Bahamas, Trinidad e Tobago, Antígua e Barbuda, Santa Lúcia, Guiana, Seicheles) e a África do Sul foram deixados de fora por decisão de escopo, restringindo a análise aos três grandes destinos.

Resultado do filtro: 36.412 voos, a partir de 3.709.917 registros lidos.

### 4.2 Chave temporal

A agregação usa `nr_ano_mes_partida_real`, o mês da partida efetiva, e não `nr_ano_mes_referencia`, o mês de referência do arquivo da ANAC.

Consequência conhecida: aparecem 20 meses no resultado, e não 19. Quatro voos do arquivo de julho de 2026 decolaram já em 1º de agosto e formam a linha residual de `2026-08`. Para eliminar esse resíduo basta trocar a chave para o mês de referência.

### 4.3 Discretização do tipo de voo

As colunas de peso (bagagem livre, bagagem em excesso, carga paga, carga grátis e correio) foram substituídas por uma classificação categórica derivada do total de passageiros a bordo:

| Categoria | Regra | Voos | Passageiros |
|---|---|---|---|
| `voo privado` | 1 a 19 passageiros | 2.536 | 16.690 |
| `voo de turismo` | 20 ou mais passageiros | 22.586 | 4.551.762 |
| `voo de carga/reabastecimento` | nenhum passageiro | 11.290 | 0 |

O corte em 19 assentos segue a fronteira regulatória da aviação, na qual aeronaves de até 19 assentos se enquadram na categoria executiva e de táxi aéreo.

A categoria de carga reúne dois casos distintos que a nomenclatura já contempla: 3.489 voos cargueiros com carga registrada e 7.801 voos de posicionamento (ferry) sem carga nem passageiros. Se a distinção entre os dois importar, o critério de separação é `kg_carga_paga` maior que zero.

### 4.4 Enriquecimento de calendário

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

A coluna `temporada` separa a demanda com mais nitidez que `estacao`, porque julho é inverno mas é pico de férias. Considerando apenas voos de turismo, férias escolares somam 268.283 passageiros por mês contra 171.408 nos meses de volta às aulas.

### 4.5 Granularidade e métricas

Cada linha do CSV final representa uma combinação de ano, mês e tipo de voo. Dentro de cada grupo são calculados:

- `qtd_voos`: contagem de trechos de voo
- `nr_passageiros`: soma de `nr_passag_pagos` mais `nr_passag_gratis`

Os passageiros grátis, que incluem tripulação e funcionários em deslocamento, foram somados junto aos pagantes por decisão de escopo.

Resultado: 59 linhas, correspondendo a 20 meses vezes 3 tipos, menos combinações inexistentes no mês residual.

## 5. Arquivo final

`data/voos_brasil_paises_ingleses.csv`

| Coluna | Tipo | Descrição |
|---|---|---|
| `ano` | inteiro | ano da partida real |
| `mes` | inteiro | mês da partida real, de 1 a 12 |
| `estacao` | texto | estação do ano no Brasil |
| `temporada` | texto | momento do calendário escolar brasileiro |
| `tipo_voo` | texto | categoria discretizada do voo |
| `qtd_voos` | inteiro | total de voos no grupo |
| `nr_passageiros` | inteiro | total de passageiros no grupo |

Totais de controle: 59 linhas, 36.412 voos e 4.568.452 passageiros.

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
        print(linha["ano"], linha["mes"], linha["tipo_voo"], linha["qtd_voos"])
```

No Excel em português, o arquivo abre corretamente com duplo clique, pois Latin-1 e ponto e vírgula são os padrões esperados pela versão brasileira. Em outras configurações regionais, use Dados, Obter Dados, De Texto/CSV e selecione origem Europeu Ocidental (ISO) e delimitador ponto e vírgula.

Os mesmos parâmetros valem para os 19 CSVs mensais limpos, que preservam as 90 colunas originais e servem para qualquer recorte diferente do adotado aqui.

## 7. Como reproduzir

Ordem de execução, a partir da raiz do projeto:

```bash
python scripts/clean_combinada.py
```

```bash
python scripts/filter_ingles.py
```

A primeira etapa lê os `.txt` e é a mais demorada, na casa de dezenas de minutos, por processar 2,9 GB em duas passadas. A segunda lê os CSVs limpos e roda em poucos minutos.

Nenhuma dependência externa é necessária. Todo o pipeline usa apenas a biblioteca padrão do Python.

Parâmetros ajustáveis, todos no topo de `scripts/filter_ingles.py`:

| Constante | Função |
|---|---|
| `PAISES_DESTINO_INGLES` | conjunto de países de destino considerados |
| `LIMITE_PRIVADO` | corte de passageiros entre voo privado e voo de turismo |
| `MES_COL` | campo usado como chave temporal |
| `ESTACAO_POR_MES` | mapa de mês para estação |
| `TEMPORADA_POR_MES` | mapa de mês para temporada escolar |