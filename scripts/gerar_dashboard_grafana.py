"""
Gera o dashboard do Grafana (JSON de importacao) sobre as tabelas gold no
Athena: grafana/dashboard_voos_x_trends.json.

O JSON e gerado por codigo para que as consultas fiquem num lugar so e possam
ser testadas localmente (scripts/testar_consultas_grafana.py roda todas elas
no DuckDB contra data/gold antes de subir para o Grafana).

Uso:
  python scripts/gerar_dashboard_grafana.py

Requisitos no Grafana (10.4 ou mais novo): plugin "Amazon Athena"
(grafana-athena-datasource) e uma fonte de dados apontando para o banco
grupo4_gold (ver grafana/README.md). Na importacao o Grafana pede para
escolher a fonte de dados Athena.
"""
import csv
import json
import os
import re

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SAIDA = os.path.join(BASE_DIR, "grafana", "dashboard_voos_x_trends.json")

DS = {"type": "grafana-athena-datasource", "uid": "${DS_ATHENA}"}

AZUL, LARANJA, VERDE_AGUA = "#2a78d6", "#eb6834", "#1baf7a"
AMARELO, MAGENTA, VERDE, VIOLETA = "#eda100", "#e87ba4", "#008300", "#6250d6"
MUDO = "#898781"
DIVERGENTE = [(None, "#184f95"), (-0.5, "#3987e5"), (-0.3, "#9ec5f4"), (-0.1, "#e1e0d9"),
              (0.1, "#f4a9a8"), (0.3, "#e34948"), (0.5, "#a02a2a")]

COMPLETAS = "semana_completa AND $__timeFilter(semana_inicio)"

TERMOS = [
    ("curso de inglês", "tr_curso_ingles"), ("aula de inglês", "tr_aula_ingles"),
    ("aprender inglês", "tr_aprender_ingles"), ("inglês online", "tr_ingles_online"),
    ("professor de inglês", "tr_professor_ingles"), ("intenção (5 termos somados)", "tr_intencao_ingles"),
    ("inglês ÷ curso online", "tr_razao_ingles_curso_online"), ("intercâmbio", "tr_intercambio"),
    ("visto americano", "tr_visto_americano"), ("passagem aérea", "tr_passagem_aerea"),
    ("curso online (controle)", "tr_curso_online"),
]
SERIES_VOOS = [("passageiros", "nr_passageiros"), ("voos", "qtd_voos"),
               ("passageiros por voo", "pax_por_voo"), ("passageiros EUA", "pax_eua"),
               ("passageiros Canadá", "pax_canada"), ("passageiros Reino Unido", "pax_reino_unido")]

GOLD_BR = os.path.join(BASE_DIR, "data", "gold", "cruzamento_semanal_br", "cruzamento_semanal_br_parte0001.csv")
RAMPA = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281", "#0d366b"]


def periodo_da_gold():
    """Anos e intervalo de tempo lidos da gold local; sem ela, o periodo original."""
    try:
        with open(GOLD_BR, encoding="utf-8") as f:
            linhas = list(csv.DictReader(f, delimiter=";"))
        anos = sorted({int(l["ano_semana"]) for l in linhas if l["semana_completa"] == "true"})
        return anos, min(l["semana_inicio"] for l in linhas), max(l["semana_fim"] for l in linhas)
    except (OSError, KeyError, ValueError):
        return [2025, 2026], "2024-12-29", "2026-08-01"


ANOS, INICIO, FIM = periodo_da_gold()


def rampa_anos(n):
    if n <= 1:
        return [RAMPA[-2]]
    return [RAMPA[round(i * (len(RAMPA) - 1) / (n - 1))] for i in range(n)]


def colunas_anos(col):
    return ",\n       ".join(f"MAX(CASE WHEN ano_semana = {a} THEN {col} END) AS \"{a}\"" for a in ANOS)


_id = [0]


def sql_raw(sql):
    """Variaveis no SQL sempre como ${nome:raw}: o Grafana insere o valor sem aspas nem escape,
    seja qual for a fonte de dados (o plugin DuckDB, por exemplo, poria aspas em todo valor)."""
    return re.sub(r"\$\{(\w+)\}", r"${\1:raw}", sql.strip())


def alvo(sql, ref="A"):
    return {"refId": ref, "datasource": DS, "format": 1, "rawSQL": sql_raw(sql),
            "connectionArgs": {"region": "__default", "catalog": "__default",
                               "database": "__default", "resultReuseEnabled": False}}


def cor(nome, hexa):
    return {"matcher": {"id": "byName", "options": nome},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": hexa}}]}


def painel(tipo, titulo, pos, sql, descricao="", defaults=None, overrides=None, options=None, **extra):
    _id[0] += 1
    p = {"id": _id[0], "type": tipo, "title": titulo, "description": descricao, "datasource": DS,
         "gridPos": dict(zip("xywh", pos)),
         "targets": [alvo(s, chr(65 + i)) for i, s in enumerate(sql if isinstance(sql, list) else [sql])],
         "fieldConfig": {"defaults": defaults or {}, "overrides": overrides or []},
         "options": options or {}}
    p.update(extra)
    return p


def linha_tempo(titulo, pos, sql, cores, descricao="", unidade="short", minimo=None, maximo=None):
    d = {"custom": {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 0, "showPoints": "never",
                    "spanNulls": False, "axisSoftMin": 0},
         "unit": unidade, "color": {"mode": "palette-classic"}}
    if minimo is not None:
        d["min"] = minimo
    if maximo is not None:
        d["max"] = maximo
    return painel("timeseries", titulo, pos, sql, descricao, d, [cor(n, c) for n, c in cores],
                  {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                   "tooltip": {"mode": "multi", "sort": "none"}})


def barras(titulo, pos, sql, x, cores, descricao="", horizontal=False, unidade="short",
           minimo=None, maximo=None, thresholds=None):
    d = {"custom": {"fillOpacity": 100, "lineWidth": 0, "gradientMode": "none",
                    "axisCenteredZero": False}, "unit": unidade, "color": {"mode": "palette-classic"}}
    if minimo is not None:
        d["min"] = minimo
    if maximo is not None:
        d["max"] = maximo
    if thresholds:
        d["color"] = {"mode": "thresholds"}
        d["thresholds"] = thresholds
    return painel("barchart", titulo, pos, sql, descricao, d, [cor(n, c) for n, c in cores],
                  {"xField": x, "orientation": "horizontal" if horizontal else "vertical",
                   "showValue": "never", "barWidth": 0.85, "groupWidth": 0.75, "stacking": "none",
                   "xTickLabelRotation": 0, "xTickLabelSpacing": 0,
                   "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                   "tooltip": {"mode": "multi", "sort": "none"}})


def stat(titulo, pos, sql, descricao="", unidade="short", decimais=None):
    d = {"unit": unidade, "color": {"mode": "fixed", "fixedColor": "text"}}
    if decimais is not None:
        d["decimals"] = decimais
    return painel("stat", titulo, pos, sql, descricao, d, [],
                  {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                   "colorMode": "none", "graphMode": "none", "textMode": "value",
                   "justifyMode": "center", "orientation": "auto"})


def limiares_divergentes():
    return {"mode": "absolute",
            "steps": [{"color": c, "value": v} for v, c in DIVERGENTE]}


def tabela(titulo, pos, sql, descricao="", colunas_corr=(), colunas_largas=None):
    overrides = []
    for c in colunas_corr:
        overrides.append({"matcher": {"id": "byName", "options": c}, "properties": [
            {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}},
            {"id": "color", "value": {"mode": "thresholds"}},
            {"id": "thresholds", "value": limiares_divergentes()},
            {"id": "decimals", "value": 2}]})
    for c, w in (colunas_largas or {}).items():
        overrides.append({"matcher": {"id": "byName", "options": c},
                          "properties": [{"id": "custom.width", "value": w}]})
    return painel("table", titulo, pos, sql, descricao,
                  {"custom": {"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False}},
                  overrides, {"showHeader": True, "cellHeight": "sm",
                              "footer": {"show": False, "reducer": ["sum"], "fields": ""}})


def linha_grupo(titulo, y):
    _id[0] += 1
    return {"id": _id[0], "type": "row", "title": titulo, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def variavel_custom(nome, rotulo, opcoes, atual, descricao=""):
    return {"type": "custom", "name": nome, "label": rotulo, "description": descricao,
            "query": ", ".join(f"{r} : {v}" for r, v in opcoes),
            "current": {"text": next(r for r, v in opcoes if v == atual), "value": atual},
            "options": [{"text": r, "value": v, "selected": v == atual} for r, v in opcoes],
            "multi": False, "includeAll": False, "hide": 0}


def paineis():
    P = []
    y = 0
    # ---------------------------------------------------------------- resumo
    P.append(linha_grupo("Resumo do período", y)); y += 1
    P += [
        stat("Passageiros no período", (0, y, 6, 4), f"""
SELECT CAST(SUM(nr_passageiros) AS bigint) AS passageiros FROM cruzamento_semanal_br WHERE {COMPLETAS}""",
             "Passageiros de voos comerciais do Brasil para EUA, Canadá e Reino Unido nas semanas "
             "completas do intervalo de tempo escolhido."),
        stat("Semanas completas no intervalo", (6, y, 6, 4), f"""
SELECT COUNT(*) AS semanas FROM cruzamento_semanal_br WHERE {COMPLETAS}"""),
        stat("Maior correlação: ${serie_voos} × ${termo}", (12, y, 6, 4), """
SELECT MAX(pearson) AS pearson FROM correlacoes
WHERE recorte = 'BR' AND serie_voos = '${serie_voos}' AND serie_trends = '${termo}'
  AND transformacao = '${transformacao}'""",
             "Maior Pearson entre a série de voos e o termo escolhidos, entre as defasagens de -8 a +8 "
             "semanas. Calculado sobre o período inteiro (não segue o seletor de tempo).", decimais=2),
        stat("Defasagem do pico (semanas)", (18, y, 6, 4), """
SELECT defasagem_semanas AS defasagem FROM correlacoes
WHERE recorte = 'BR' AND serie_voos = '${serie_voos}' AND serie_trends = '${termo}'
  AND transformacao = '${transformacao}'
ORDER BY pearson DESC LIMIT 1""",
             "Positivo: a busca acontece depois do voo. Negativo: a busca vem antes.", decimais=0),
    ]
    y += 4
    # ------------------------------------------------------- series semanais
    P.append(linha_grupo("Séries semanais", y)); y += 1
    P.append(linha_tempo("Passageiros × ${termo:text} (índice 0 a 100)", (0, y, 24, 9), f"""
SELECT CAST(semana_inicio AS timestamp) AS time,
       pax_indice AS "Passageiros (índice)",
       ${{termo}} AS "Busca: ${{termo:text}}",
       tr_curso_online AS "Busca: curso online (controle)"
FROM cruzamento_semanal_br WHERE {COMPLETAS} ORDER BY 1""",
        [("Passageiros (índice)", AZUL), ("Busca: ${termo:text}", LARANJA),
         ("Busca: curso online (controle)", VERDE_AGUA)],
        "As três séries na mesma base (100 = maior semana de cada uma no período), sem eixo duplo. "
        "Troque o termo no seletor do topo.", minimo=0, maximo=100))
    y += 9
    P.append(linha_tempo("Termos de intenção de estudar inglês", (0, y, 12, 8), f"""
SELECT CAST(semana_inicio AS timestamp) AS time,
       tr_curso_ingles AS "curso de inglês", tr_aula_ingles AS "aula de inglês",
       tr_aprender_ingles AS "aprender inglês", tr_ingles_online AS "inglês online",
       tr_professor_ingles AS "professor de inglês"
FROM cruzamento_semanal_br WHERE {COMPLETAS} ORDER BY 1""",
        [("curso de inglês", LARANJA), ("aula de inglês", AZUL), ("aprender inglês", VERDE_AGUA),
         ("inglês online", AMARELO), ("professor de inglês", MAGENTA)],
        "Mesma escala entre os cinco termos (100 = maior semana de curso de inglês).", minimo=0))
    P.append(linha_tempo("Contexto de viagem e controle", (12, y, 12, 8), f"""
SELECT CAST(semana_inicio AS timestamp) AS time,
       tr_passagem_aerea AS "passagem aérea", tr_visto_americano AS "visto americano",
       tr_intercambio AS "intercâmbio", tr_curso_online AS "curso online"
FROM cruzamento_semanal_br WHERE {COMPLETAS} ORDER BY 1""",
        [("passagem aérea", AZUL), ("visto americano", LARANJA), ("intercâmbio", VERDE_AGUA),
         ("curso online", AMARELO)],
        "Mesma escala entre os termos do grupo (100 = maior semana de curso online).", minimo=0))
    y += 8
    P.append(linha_tempo("Passageiros por destino", (0, y, 12, 8), f"""
SELECT CAST(semana_inicio AS timestamp) AS time,
       pax_eua AS "EUA", pax_reino_unido AS "Reino Unido", pax_canada AS "Canadá"
FROM cruzamento_semanal_br WHERE {COMPLETAS} ORDER BY 1""",
        [("EUA", AZUL), ("Reino Unido", LARANJA), ("Canadá", VERDE_AGUA)], minimo=0))
    P.append(linha_tempo("Ocupação: passageiros por voo", (12, y, 12, 8), f"""
SELECT CAST(semana_inicio AS timestamp) AS time, pax_por_voo AS "passageiros por voo"
FROM cruzamento_semanal_br WHERE {COMPLETAS} ORDER BY 1""",
        [("passageiros por voo", AZUL)],
        "Separa o pico que vem de mais voos do pico que vem de voos mais cheios."))
    y += 8
    # ------------------------------------------------------------ correlacoes
    P.append(linha_grupo("Correlações", y)); y += 1
    P.append(barras("Correlograma: ${serie_voos:text} × ${termo:text}", (0, y, 12, 9), """
SELECT CAST(defasagem_semanas AS varchar) AS "defasagem (semanas)",
       pearson AS "Pearson",
       CASE WHEN significativo THEN pearson END AS "Pearson significativo (5%)"
FROM correlacoes
WHERE recorte = 'BR' AND serie_voos = '${serie_voos}' AND serie_trends = '${termo}'
  AND transformacao = '${transformacao}'
ORDER BY defasagem_semanas""", "defasagem (semanas)",
        [("Pearson", "#9ec5f4"), ("Pearson significativo (5%)", AZUL)],
        "Voos na semana t contra busca na semana t+k. Positivo: a busca vem depois. A significância "
        "usa o tamanho efetivo da amostra, que desconta a autocorrelação das séries semanais.",
        minimo=-1, maximo=1))
    P.append(painel("xychart", "Dispersão: ${serie_voos:text} na semana t × ${termo:text} na semana t+${defasagem}",
                    (12, y, 12, 9), f"""
SELECT a.${{serie_voos}} AS "${{serie_voos:text}} (semana t)",
       b.${{termo}} AS "${{termo:text}} (semana t+k)"
FROM cruzamento_semanal_br a
JOIN cruzamento_semanal_br b ON b.semana_inicio = date_add('week', ${{defasagem}}, a.semana_inicio)
WHERE a.semana_completa AND b.semana_completa
  AND $__timeFilter(a.semana_inicio)""",
                    "Cada ponto é uma semana. Mude a defasagem no seletor do topo.",
                    {"custom": {"show": "points", "pointSize": {"fixed": 7}},
                     "color": {"mode": "fixed", "fixedColor": AZUL}}, [],
                    {"mapping": "auto", "seriesMapping": "auto", "series": [{}],
                     "legend": {"showLegend": False, "displayMode": "list", "placement": "bottom"},
                     "tooltip": {"mode": "single", "sort": "none"}}))
    y += 9
    colunas = ", ".join(
        f"ROUND(MAX(CASE WHEN serie_voos = '{v}' THEN pearson END), 2) AS \"{r}\"" for r, v in SERIES_VOOS)
    ordem = " ".join(f"WHEN '{v}' THEN {i}" for i, (_, v) in enumerate(TERMOS))
    nomes = " ".join(f"WHEN '{v}' THEN '{r}'" for r, v in TERMOS)
    P.append(tabela("Matriz de correlação (defasagem ${defasagem} semanas, ${transformacao})", (0, y, 24, 10), f"""
SELECT CASE serie_trends {nomes} END AS "termo do Trends", {colunas}
FROM correlacoes
WHERE recorte = 'BR' AND transformacao = '${{transformacao}}' AND defasagem_semanas = ${{defasagem}}
GROUP BY serie_trends
ORDER BY CASE serie_trends {ordem} END""",
        "Pearson entre cada série de voos (colunas) e cada termo do Trends (linhas). Azul: relação "
        "inversa; vermelho: relação direta. Use a defasagem 0 para a mesma semana.",
        [r for r, _ in SERIES_VOOS], {"termo do Trends": 220}))
    y += 10
    P.append(tabela("Ranking dos pares mais correlacionados (${transformacao})", (0, y, 24, 10), f"""
SELECT recorte, serie_voos AS "série de voos", serie_trends AS "termo",
       defasagem_semanas AS "defasagem", ROUND(pearson, 3) AS "Pearson",
       ROUND(spearman, 3) AS "Spearman", n, ROUND(n_efetivo, 1) AS "n efetivo",
       CASE WHEN significativo THEN 'sim' ELSE 'não' END AS "significativo (5%)"
FROM correlacoes
WHERE transformacao = '${{transformacao}}'
ORDER BY ABS(pearson) DESC
LIMIT 30""",
        "Todos os recortes (Brasil e UFs), todas as defasagens. Correlação alta sem significância "
        "é efeito de poucas semanas independentes.", ["Pearson", "Spearman"]))
    y += 10
    # ------------------------------------------------------------- calendario
    P.append(linha_grupo("Calendário escolar e ano contra ano", y)); y += 1
    P.append(barras("Cada série por temporada (100 = média do período)", (0, y, 12, 9), f"""
SELECT temporada,
       ROUND(100 * AVG(nr_passageiros) / (SELECT AVG(nr_passageiros) FROM cruzamento_semanal_br WHERE {COMPLETAS}), 1) AS "passageiros",
       ROUND(100 * AVG(tr_curso_ingles) / (SELECT AVG(tr_curso_ingles) FROM cruzamento_semanal_br WHERE {COMPLETAS}), 1) AS "curso de inglês",
       ROUND(100 * AVG(tr_aula_ingles) / (SELECT AVG(tr_aula_ingles) FROM cruzamento_semanal_br WHERE {COMPLETAS}), 1) AS "aula de inglês",
       ROUND(100 * AVG(tr_curso_online) / (SELECT AVG(tr_curso_online) FROM cruzamento_semanal_br WHERE {COMPLETAS}), 1) AS "curso online"
FROM cruzamento_semanal_br WHERE {COMPLETAS}
GROUP BY temporada
ORDER BY CASE temporada WHEN 'férias escolares' THEN 1 WHEN 'volta às aulas' THEN 2 ELSE 3 END""",
        "temporada", [("passageiros", AZUL), ("curso de inglês", LARANJA), ("aula de inglês", VERDE_AGUA),
                      ("curso online", AMARELO)],
        "Acima de 100: a série fica acima da própria média naquela temporada. Passageiros e curso de "
        "inglês sobem nas férias; aula de inglês cai.", minimo=0))
    for i, (col, rotulo) in enumerate([("nr_passageiros", "Passageiros"), ("${termo}", "${termo:text}")]):
        P.append(painel("trend", f"{rotulo} por semana do ano", (12 + 6 * i, y, 6, 9), f"""
SELECT num_semana AS "semana do ano",
       {colunas_anos(col)}
FROM cruzamento_semanal_br WHERE semana_completa
GROUP BY num_semana ORDER BY num_semana""",
            "Sobreposição ano a ano: picos alinhados na mesma semana indicam sazonalidade, não evento pontual.",
            {"custom": {"lineWidth": 2, "showPoints": "never", "spanNulls": False, "fillOpacity": 0},
             "color": {"mode": "palette-classic"}},
            [cor(str(a), c) for a, c in zip(ANOS, rampa_anos(len(ANOS)))],
            {"xField": "semana do ano", "legend": {"displayMode": "list", "placement": "bottom",
                                                    "showLegend": True},
             "tooltip": {"mode": "multi", "sort": "none"}}))
    y += 9
    # --------------------------------------------------------------- regional
    P.append(linha_grupo("Regional (UF do aeroporto de embarque)", y)); y += 1
    P.append(dict(linha_tempo("${uf}: passageiros × busca por curso de inglês (índice)", (0, y, 8, 8), f"""
SELECT CAST(semana_inicio AS timestamp) AS time,
       ROUND(100.0 * nr_passageiros / MAX(nr_passageiros) OVER (), 2) AS "passageiros (índice)",
       ROUND(100.0 * tr_curso_ingles_uf / MAX(tr_curso_ingles_uf) OVER (), 2) AS "busca na UF (índice)"
FROM cruzamento_semanal_uf
WHERE sg_uf = '${{uf}}' AND {COMPLETAS}
ORDER BY 1""", [("passageiros (índice)", AZUL), ("busca na UF (índice)", LARANJA)],
        "Um gráfico por UF escolhida no seletor. 100 = maior semana da UF. Semanas sem dado no "
        "Trends ficam em branco (volume abaixo do limiar de privacidade do Google).",
        minimo=0, maximo=100), repeat="uf", repeatDirection="h", maxPerRow=3))
    y += 8
    P.append(barras("Correlograma por UF: passageiros × busca na UF", (0, y, 12, 9), """
SELECT CAST(defasagem_semanas AS varchar) AS "defasagem (semanas)",
       MAX(CASE WHEN recorte = 'SP' THEN pearson END) AS "SP",
       MAX(CASE WHEN recorte = 'RJ' THEN pearson END) AS "RJ",
       MAX(CASE WHEN recorte = 'MG' THEN pearson END) AS "MG"
FROM correlacoes
WHERE serie_voos = 'nr_passageiros' AND serie_trends = 'tr_curso_ingles_uf'
  AND transformacao = '${transformacao}'
GROUP BY defasagem_semanas ORDER BY defasagem_semanas""", "defasagem (semanas)",
        [("SP", AZUL), ("RJ", LARANJA), ("MG", VERDE_AGUA)],
        "Só UFs com voo comercial e série semanal do Trends com dado suficiente.", minimo=-1, maximo=1))
    P.append(barras("Interesse por curso de inglês, por UF", (12, y, 12, 9), """
SELECT sg_uf AS "UF", interesse_curso_ingles AS "interesse (100 = maior UF)"
FROM resumo_uf ORDER BY interesse_curso_ingles DESC""", "UF",
        [("interesse (100 = maior UF)", AZUL)],
        "Busca relativa no período inteiro: participação de curso de inglês no total de buscas da UF.",
        minimo=0, maximo=100))
    y += 9
    P.append(tabela("Resumo por UF", (0, y, 24, 9), """
SELECT sg_uf AS "UF", nome_uf AS "nome", regiao AS "região", qtd_voos AS "voos",
       nr_passageiros AS "passageiros", pct_passageiros AS "% dos passageiros",
       interesse_curso_ingles AS "interesse no Trends",
       CASE WHEN serie_semanal_trends THEN 'sim' ELSE 'não' END AS "série semanal no Trends",
       semanas_com_dado_trends AS "semanas com dado", ROUND(pearson_semanal, 2) AS "Pearson semanal"
FROM resumo_uf ORDER BY nr_passageiros DESC, interesse_curso_ingles DESC""",
        "Voos e passageiros contam a UF do aeroporto de embarque, não a residência do passageiro: "
        "Guarulhos (SP) recebe conexões do país inteiro.", ["Pearson semanal"]))
    y += 9
    P += paineis_destinos(y)
    return P


SEGMENTOS = [("Anglófonos", "anglofono", AZUL), ("Não anglófonos", "nao_anglofono", LARANJA),
             ("América do Sul", "nao_anglofono_america_sul", VERDE_AGUA),
             ("Europa", "nao_anglofono_europa", AMARELO)]
TERMOS_DESTINOS = [("curso de inglês", "tr_curso_ingles"), ("intenção (5 termos somados)", "tr_intencao_ingles"),
                   ("aula de inglês", "tr_aula_ingles"), ("curso online (controle)", "tr_curso_online"),
                   ("inglês ÷ curso online", "tr_razao_ingles_curso_online")]


def paineis_destinos(y):
    """Grupo de comparacao: ferias ou destino? Tabelas *_destinos da gold."""
    P = [linha_grupo("Férias ou destino? (grupo de comparação: destinos não anglófonos)", y)]
    y += 1
    pivo = ",\n       ".join(
        f"MAX(CASE WHEN segmento = '{v}' THEN pax_indice END) AS \"{r}\"" for r, v, _ in SEGMENTOS)
    P.append(linha_tempo("Passageiros por destino (índice) × ${termo_destinos:text}", (0, y, 24, 9), f"""
SELECT CAST(semana_inicio AS timestamp) AS time,
       {pivo},
       MAX(${{termo_destinos}}) AS "Busca: ${{termo_destinos:text}}"
FROM comparacao_destinos_semanal
WHERE {COMPLETAS}
GROUP BY semana_inicio ORDER BY 1""",
        [(r, c) for r, _, c in SEGMENTOS] + [("Busca: ${termo_destinos:text}", MUDO)],
        "Cada grupo de destino em índice (100 = maior semana do grupo). A Europa, que não segue as "
        "férias escolares brasileiras, é o contraste.", minimo=30, maximo=100))
    P[-1]["fieldConfig"]["overrides"].append({
        "matcher": {"id": "byName", "options": "Busca: ${termo_destinos:text}"},
        "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [8, 6]}}]})
    y += 9
    pivo_corr = ",\n       ".join(
        f"MAX(CASE WHEN segmento = '{v}' THEN pearson END) AS \"{r}\"" for r, v, _ in SEGMENTOS)
    P.append(barras("Correlograma por destino: passageiros × ${termo_destinos:text}", (0, y, 12, 9), f"""
SELECT CAST(defasagem_semanas AS varchar) AS "defasagem (semanas)",
       {pivo_corr}
FROM correlacoes_destinos
WHERE serie_voos = 'nr_passageiros' AND serie_trends = '${{termo_destinos}}'
  AND transformacao = '${{transformacao}}'
GROUP BY defasagem_semanas ORDER BY defasagem_semanas""", "defasagem (semanas)",
        [(r, c) for r, _, c in SEGMENTOS],
        "Se o efeito fosse só do destino de língua inglesa, os não anglófonos não teriam correlação. "
        "Positivo: a busca vem depois do voo.", minimo=-1, maximo=1))
    P.append(barras("Correlação parcial: o que cada grupo acrescenta sobre o outro", (12, y, 12, 9), """
SELECT CAST(defasagem_semanas AS varchar) AS "defasagem (semanas)",
       MAX(CASE WHEN explicativa = 'anglofono' THEN pearson_parcial END) AS "anglófonos, descontados os não anglófonos",
       MAX(CASE WHEN explicativa = 'nao_anglofono' THEN pearson_parcial END) AS "não anglófonos, descontados os anglófonos"
FROM parciais_destinos
WHERE serie_trends = '${termo_destinos}'
GROUP BY defasagem_semanas ORDER BY defasagem_semanas""", "defasagem (semanas)",
        [("anglófonos, descontados os não anglófonos", AZUL),
         ("não anglófonos, descontados os anglófonos", LARANJA)],
        "Correlação de cada grupo com a busca depois de retirar o que o outro grupo explica.",
        minimo=-1, maximo=1))
    y += 9
    P.append(painel("xychart", "Composição: % anglófona dos passageiros (semana t) × ${termo_destinos:text} (t+${defasagem})",
                    (0, y, 12, 9), f"""
SELECT a.participacao_pax AS "% anglófona (semana t)",
       b.${{termo_destinos}} AS "${{termo_destinos:text}} (semana t+k)"
FROM comparacao_destinos_semanal a
JOIN comparacao_destinos_semanal b
  ON b.segmento = a.segmento AND b.semana_inicio = date_add('week', ${{defasagem}}, a.semana_inicio)
WHERE a.segmento = 'anglofono' AND a.semana_completa AND b.semana_completa
  AND $__timeFilter(a.semana_inicio)""",
                    "Se o destino importasse, semanas com mais viagem para países de língua inglesa (em "
                    "proporção) seriam seguidas de mais busca. Não são.",
                    {"custom": {"show": "points", "pointSize": {"fixed": 7}},
                     "color": {"mode": "fixed", "fixedColor": AZUL}}, [],
                    {"mapping": "auto", "seriesMapping": "auto", "series": [{}],
                     "legend": {"showLegend": False, "displayMode": "list", "placement": "bottom"},
                     "tooltip": {"mode": "single", "sort": "none"}}))
    P.append(tabela("Pico de correlação por destino (${transformacao})", (12, y, 12, 9), """
SELECT c.segmento AS "segmento", c.serie_voos AS "série", c.defasagem_semanas AS "defasagem do pico",
       c.pearson AS "Pearson", CASE WHEN c.significativo THEN 'sim' ELSE 'não' END AS "significativo (5%)"
FROM correlacoes_destinos c
JOIN (SELECT segmento, serie_voos, MAX(pearson) AS maximo FROM correlacoes_destinos
      WHERE serie_trends = '${termo_destinos}' AND transformacao = '${transformacao}'
      GROUP BY segmento, serie_voos) m
  ON m.segmento = c.segmento AND m.serie_voos = c.serie_voos AND m.maximo = c.pearson
WHERE c.serie_trends = '${termo_destinos}' AND c.transformacao = '${transformacao}'
ORDER BY c.pearson DESC""",
        "nr_passageiros: volume do grupo; participacao_pax: fatia do grupo no total internacional.",
        ["Pearson"]))
    return P


def dashboard():
    termos = [(r, v) for r, v in TERMOS]
    return {
        "__inputs": [{"name": "DS_ATHENA", "label": "Athena", "type": "datasource",
                      "pluginId": "grafana-athena-datasource", "pluginName": "Amazon Athena"}],
        "__requires": [{"type": "datasource", "id": "grafana-athena-datasource", "name": "Amazon Athena",
                        "version": "2.0.0"},
                       {"type": "grafana", "id": "grafana", "name": "Grafana", "version": "10.4.0"}],
        "title": "Voos para países anglófonos × intenção de estudar inglês",
        "uid": "grupo4-voos-trends",
        "description": "Projeto Boost Your English, grupo 4. Cruzamento semanal entre voos comerciais "
                       "do Brasil para EUA, Canadá e Reino Unido (ANAC) e interesse de busca (Google Trends).",
        "tags": ["grupo4", "anac", "google-trends", "boost-your-english"],
        "timezone": "browser",
        "editable": True,
        "graphTooltip": 1,
        "time": {"from": f"{INICIO}T00:00:00.000Z", "to": f"{FIM}T23:59:59.000Z"},
        "timepicker": {},
        "schemaVersion": 39,
        "version": 1,
        "refresh": "",
        "templating": {"list": [
            variavel_custom("termo", "Termo do Trends", termos, "tr_curso_ingles"),
            variavel_custom("serie_voos", "Série de voos", SERIES_VOOS, "nr_passageiros"),
            variavel_custom("transformacao", "Transformação",
                            [("nível", "nivel"), ("variação semanal", "variacao")], "nivel",
                            "Nível compara os valores; variação compara as mudanças de uma semana "
                            "para a outra, o que tira tendência e sazonalidade comum."),
            variavel_custom("termo_destinos", "Termo (comparação de destinos)", TERMOS_DESTINOS,
                            "tr_curso_ingles"),
            variavel_custom("defasagem", "Defasagem (semanas)",
                            [(str(k), str(k)) for k in range(-8, 9)], "3",
                            "Positivo: a busca vem k semanas depois do voo."),
            {"type": "query", "name": "uf", "label": "UF", "datasource": DS,
             "query": {"rawSQL": "SELECT DISTINCT sg_uf FROM cruzamento_semanal_uf "
                                 "WHERE cruzamento = 'voos e trends' ORDER BY sg_uf", "format": 1,
                       "connectionArgs": {"region": "__default", "catalog": "__default",
                                          "database": "__default"}},
             "definition": "SELECT DISTINCT sg_uf FROM cruzamento_semanal_uf WHERE cruzamento = 'voos e trends'",
             "refresh": 1, "multi": True, "includeAll": False,
             "current": {"text": ["SP", "RJ", "MG"], "value": ["SP", "RJ", "MG"]}, "hide": 0, "sort": 1},
        ]},
        "annotations": {"list": [
            {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True,
             "hide": True, "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts",
             "type": "dashboard"},
            {"datasource": DS, "enable": True, "hide": False, "iconColor": MUDO,
             "name": "Eventos de calendário",
             "target": alvo("SELECT CAST(semana_inicio AS timestamp) AS time, evento AS text "
                            "FROM cruzamento_semanal_br WHERE evento <> '' "
                            "AND $__timeFilter(semana_inicio)")},
        ]},
        "panels": paineis(),
    }


DS_LOCAL = {"type": "motherduck-duckdb-datasource", "uid": "duckdb-gold"}
SAIDA_LOCAL = os.path.join(BASE_DIR, "grafana", "local", "provisioning", "dashboards",
                           "dashboard_voos_x_trends_local.json")


def sql_local(sql):
    """Athena (Trino) -> DuckDB. Sem filtro de tempo: a versao local mostra o periodo inteiro."""
    sql = re.sub(r"\$__timeFilter\((?:[^()]|\([^()]*\))*\)", "TRUE", sql)
    return re.sub(r"date_add\('week',\s*(\$\{\w+(?::\w+)?\}|-?\d+),\s*([\w.]+)\)", r"(\2 + to_weeks(\1))", sql)


def para_local(no):
    """Versao do dashboard para o Grafana local com o plugin DuckDB (grafana/local)."""
    if isinstance(no, list):
        return [para_local(x) for x in no]
    if not isinstance(no, dict):
        return no
    if no.get("type") == "grafana-athena-datasource" and "uid" in no:
        return dict(DS_LOCAL)
    if "rawSQL" in no:
        return {"refId": no.get("refId", "A"), "datasource": dict(DS_LOCAL), "editorMode": "code",
                "format": 1, "rawQuery": True, "rawSql": sql_local(no["rawSQL"])}
    if no.get("name") == "uf" and no.get("type") == "query":
        ufs = ["SP", "RJ", "MG"]
        return {"type": "custom", "name": "uf", "label": "UF", "query": ",".join(ufs),
                "multi": True, "includeAll": False, "hide": 0,
                "current": {"text": ufs, "value": ufs},
                "options": [{"text": u, "value": u, "selected": True} for u in ufs]}
    return {k: para_local(v) for k, v in no.items() if k not in ("__inputs", "__requires")}


def main():
    d = dashboard()
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print(f"Gravado: {os.path.relpath(SAIDA, BASE_DIR)} ({len(d['panels'])} painéis e linhas)")

    local = para_local(d)
    local["uid"] = "grupo4-voos-trends-local"
    local["title"] += " (local, DuckDB)"
    local["description"] += " Versão local: lê os CSVs de data/gold pelo plugin DuckDB, sem AWS."
    os.makedirs(os.path.dirname(SAIDA_LOCAL), exist_ok=True)
    with open(SAIDA_LOCAL, "w", encoding="utf-8") as f:
        json.dump(local, f, ensure_ascii=False, indent=2)
    print(f"Gravado: {os.path.relpath(SAIDA_LOCAL, BASE_DIR)}")


if __name__ == "__main__":
    main()
