"""
Roda todas as consultas do dashboard do Grafana no DuckDB, contra os CSVs de
data/gold, para pegar erro de SQL antes de importar o dashboard.

O Athena usa o dialeto do Trino. As consultas do dashboard foram escritas no
subconjunto comum ao Trino e ao DuckDB; as unicas traducoes feitas aqui sao a
macro $__timeFilter (vira TRUE) e date_add('week', k, x) (vira x + k semanas).
Cada variavel e testada em todos os valores possiveis.

Testa o dashboard do Athena e a versao local (grafana/local).

Uso:
  pip install duckdb
  python scripts/testar_consultas_grafana.py
"""
import itertools
import json
import os
import re
import sys

import duckdb

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
GOLD = os.path.join(BASE_DIR, "data", "gold")
DASHBOARDS = [os.path.join(BASE_DIR, "grafana", "dashboard_voos_x_trends.json"),
              os.path.join(BASE_DIR, "grafana", "local", "provisioning", "dashboards",
                           "dashboard_voos_x_trends_local.json")]
TABELAS = ["cruzamento_semanal_br", "cruzamento_semanal_uf", "resumo_uf", "correlacoes",
           "comparacao_destinos_semanal", "correlacoes_destinos", "parciais_destinos"]


def conectar():
    con = duckdb.connect()
    for t in TABELAS:
        caminho = os.path.join(GOLD, t, f"{t}_parte0001.csv").replace("\\", "/")
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_csv('{caminho}', delim=';', header=true)")
    return con


def consultas(dash):
    for p in dash["panels"]:
        for t in p.get("targets", []):
            yield p["title"], t.get("rawSQL") or t["rawSql"]
    for a in dash["annotations"]["list"]:
        if "target" in a:
            yield "anotação: " + a["name"], a["target"].get("rawSQL") or a["target"]["rawSql"]
    for v in dash["templating"]["list"]:
        if v["type"] == "query":
            yield "variável: " + v["name"], v["query"]["rawSQL"]


def para_duckdb(sql):
    sql = re.sub(r"\$__timeFilter\((?:[^()]|\([^()]*\))*\)", "TRUE", sql)
    return re.sub(r"date_add\('week',\s*(-?\d+),\s*([\w.]+)\)", r"(\2 + to_weeks(\1))", sql)


def main():
    con = conectar()
    falhas = total = 0
    for caminho in DASHBOARDS:
        f, t = testar(con, json.load(open(caminho, encoding="utf-8")))
        print(f"{os.path.relpath(caminho, BASE_DIR)}: {t} execuções, {f} falha(s)")
        falhas, total = falhas + f, total + t
    sys.exit(1 if falhas else 0)


def testar(con, dash):
    opcoes = {v["name"]: [(o["text"], o["value"]) for o in v.get("options", [])]
              for v in dash["templating"]["list"] if v["type"] == "custom"}
    opcoes["uf"] = [(u, u) for u in ("SP", "RJ", "MG")]
    falhas, total = 0, 0
    for titulo, sql in consultas(dash):
        usadas = sorted(set(re.findall(r"\$\{(\w+)(?::\w+)?\}", sql)))
        for combo in itertools.product(*[opcoes[u] for u in usadas]):
            s = sql
            for nome, (texto, valor) in zip(usadas, combo):
                s = (s.replace(f"${{{nome}:text}}", texto).replace(f"${{{nome}:raw}}", valor)
                     .replace(f"${{{nome}}}", valor))
            total += 1
            try:
                df = con.execute(para_duckdb(s)).df()
                nulas = [c for c in df.columns if df[c].isna().all() and "significativo" not in c]
                if df.empty or nulas:
                    raise ValueError(f"resultado vazio ou coluna toda nula: {nulas or list(df.columns)}")
            except Exception as e:
                falhas += 1
                print(f"FALHA [{titulo}] {dict(zip(usadas, (v for _, v in combo)))}: {e}")
                break
    return falhas, total


if __name__ == "__main__":
    main()
