"""
Coleta no Google Trends a serie semanal de interesse de busca por aulas de
ingles (e termos de contexto) e grava os arquivos da camada bronze.

Usa os mesmos endpoints que a pagina "Explorar" do Trends chama no navegador:
  1. POST /trends/api/explore            -> devolve os widgets e seus tokens
  2. GET  /trends/api/widgetdata/multiline  -> serie temporal (TIMESERIES)
  3. GET  /trends/api/widgetdata/comparedgeo -> interesse por UF (GEO_MAP)
Nao ha API oficial aberta (a oficial segue em alpha com acesso restrito), e o
pytrends, que faz o mesmo, esta arquivado. Por isso o cliente e proprio e
pequeno: so requests, com espera entre chamadas e nova tentativa em 429.

Saida (bronze), UTF-8, separador ';', uma linha por semana x termo x geo.
A pasta data/bronze espelha a raiz do bucket bronze:
  data/bronze/google_trends/series/<grupo>/<grupo>_<inicio>_<fim>.csv
  data/bronze/google_trends/mapa_uf/mapa_uf_<inicio>_<fim>.csv

Cada arquivo de serie e uma requisicao: os valores de 0 a 100 so sao
comparaveis dentro do mesmo arquivo. A emenda entre janelas e a escala unica
sao feitas no job glue_trends_bronze_para_silver.py (METODOLOGIA.md, secao 10).

Uso:
  pip install requests
  python scripts/coletar_google_trends.py                 # todas as consultas
  python scripts/coletar_google_trends.py --grupo uf_curso_ingles
  python scripts/coletar_google_trends.py --inicio 2024-12-29 --fim 2026-08-01

Os arquivos ficam abaixo de 600 KB e podem ir direto para o bucket bronze
pela Lambda. Se o Google responder 429 em sequencia, espere algumas horas ou
troque de rede: o limite e por IP.
"""
import argparse
import csv
import datetime as dt
import json
import os
import random
import sys
import time

import requests

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SAIDA = os.path.join(BASE_DIR, "data", "bronze", "google_trends")
URL = "https://trends.google.com"
HL, TZ = "pt-BR", "180"          # horario de Brasilia (UTC-3)

INICIO_PADRAO = "2024-12-29"     # domingo da semana de 01/01/2025
FIM_PADRAO = "2026-08-01"        # sabado da semana de 31/07/2026
DIAS_JANELA = 300                # acima de 270 dias o Trends devolve dado semanal
DIAS_MAX_UMA_JANELA = 1800       # ate ~5 anos o Trends ainda devolve semanal numa requisicao so
SOBREPOSICAO_SEMANAS = 3         # semanas repetidas entre janelas, usadas na emenda

# Ate 5 itens por requisicao (limite do Trends). Termos de um mesmo grupo saem
# na mesma escala, o que permite compara-los e soma-los.
CONSULTAS = [
    {
        "grupo": "intencao_ingles",
        "termos": ["curso de inglês", "aula de inglês", "aprender inglês",
                   "inglês online", "professor de inglês"],
        "geos": ["BR"],
    },
    {
        "grupo": "contexto_viagem",
        # curso de ingles repete como ancora; curso online e o controle
        # (calendario educacional generico); visto, passagem e intercambio
        # medem intencao de viagem.
        "termos": ["curso de inglês", "intercâmbio", "visto americano",
                   "passagem aérea", "curso online"],
        "geos": ["BR"],
    },
    {
        "grupo": "uf_curso_ingles",
        # Mesmo termo em 5 UFs, na mesma escala. UFs com voos comerciais para
        # os tres destinos e volume de busca suficiente para dado semanal.
        "termos": ["curso de inglês"],
        "geos": ["BR-SP", "BR-RJ", "BR-MG", "BR-DF", "BR-PR"],
    },
]
TERMO_MAPA = "curso de inglês"   # interesse por UF no periodo inteiro (27 UFs)

COLUNAS_SERIE = ["grupo", "termo", "geo", "janela_inicio", "janela_fim",
                 "semana_inicio", "valor", "tem_dado", "parcial", "coletado_em"]
COLUNAS_MAPA = ["grupo", "termo", "geo_pai", "janela_inicio", "janela_fim",
                "geo_code", "geo_nome", "valor", "tem_dado", "coletado_em"]


def janelas(inicio, fim, dias=DIAS_JANELA, sobreposicao=SOBREPOSICAO_SEMANAS):
    """Divide o periodo em janelas de ~dias, sobrepostas em N semanas.

    O inicio de cada janela e um domingo, para cair no inicio da semana do
    Trends. Janelas menores que 270 dias voltariam com dado diario, entao a
    ultima e esticada para tras quando necessario.
    """
    ini, fim = dt.date.fromisoformat(inicio), dt.date.fromisoformat(fim)
    if 270 < (fim - ini).days <= DIAS_MAX_UMA_JANELA and dias == DIAS_JANELA:
        return [(ini.isoformat(), fim.isoformat())]
    saida = []
    while True:
        fim_j = min(ini + dt.timedelta(days=dias), fim)
        if (fim_j - ini).days < 270:
            ini = fim_j - dt.timedelta(days=dias)
            ini -= dt.timedelta(days=(ini.weekday() + 1) % 7)
        saida.append((ini.isoformat(), fim_j.isoformat()))
        if fim_j >= fim:
            return saida
        ini = fim_j - dt.timedelta(weeks=sobreposicao) + dt.timedelta(days=1)
        ini -= dt.timedelta(days=(ini.weekday() + 1) % 7)


class Trends:
    def __init__(self, espera=(20, 40), tentativas=5):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                                        "Chrome/141.0 Safari/537.36")
        self.espera, self.tentativas = espera, tentativas
        self._get(f"{URL}/trends/?geo=BR&hl={HL}", json_resp=False)   # cookie NID

    def _get(self, url, params=None, metodo="GET", json_resp=True):
        for n in range(1, self.tentativas + 1):
            r = self.s.request(metodo, url, params=params, timeout=30)
            if r.status_code == 200:
                time.sleep(random.uniform(*self.espera))
                if not json_resp:
                    return r.text
                texto = r.text
                return json.loads(texto[texto.index("{"):])   # remove o prefixo )]}'
            if r.status_code != 429:
                r.raise_for_status()
            pausa = 60 * 2 ** (n - 1)
            print(f"  429 do Google, nova tentativa em {pausa}s ({n}/{self.tentativas})", flush=True)
            time.sleep(pausa)
        raise SystemExit("O Google continua respondendo 429. Tente mais tarde ou de outra rede.")

    def explorar(self, itens, janela):
        tempo = f"{janela[0]} {janela[1]}"
        req = {"comparisonItem": [{"keyword": t, "geo": g, "time": tempo} for t, g in itens],
               "category": 0, "property": ""}
        resp = self._get(f"{URL}/trends/api/explore", metodo="POST",
                         params={"hl": HL, "tz": TZ, "req": json.dumps(req, ensure_ascii=False)})
        return {w["id"]: w for w in resp["widgets"]}

    def serie(self, widget):
        resp = self._get(f"{URL}/trends/api/widgetdata/multiline", params={
            "hl": HL, "tz": TZ, "token": widget["token"],
            "req": json.dumps(widget["request"], ensure_ascii=False)})
        if widget["request"].get("resolution") != "WEEK":
            raise SystemExit(f"Resolucao {widget['request'].get('resolution')} em vez de WEEK; "
                             "a janela precisa ter mais de 270 dias")
        return resp["default"]["timelineData"]

    def mapa(self, widget):
        resp = self._get(f"{URL}/trends/api/widgetdata/comparedgeo", params={
            "hl": HL, "tz": TZ, "token": widget["token"],
            "req": json.dumps(widget["request"], ensure_ascii=False)})
        return resp["default"]["geoMapData"]


def semana(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).date().isoformat()


def gravar(caminho, colunas, linhas):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=colunas, delimiter=";", lineterminator="\n")
        w.writeheader()
        w.writerows(linhas)
    print(f"  gravado {os.path.relpath(caminho, BASE_DIR)} ({len(linhas)} linhas)", flush=True)


def coletar_serie(tr, consulta, janela, hoje):
    itens = [(t, g) for g in consulta["geos"] for t in consulta["termos"]]
    if len(itens) > 5:
        raise SystemExit(f"{consulta['grupo']}: no maximo 5 combinacoes termo x geo por requisicao")
    widgets = tr.explorar(itens, janela)
    linhas = []
    for ponto in tr.serie(widgets["TIMESERIES"]):
        for i, (termo, geo) in enumerate(itens):
            linhas.append({
                "grupo": consulta["grupo"], "termo": termo, "geo": geo,
                "janela_inicio": janela[0], "janela_fim": janela[1],
                "semana_inicio": semana(ponto["time"]),
                "valor": ponto["value"][i] if ponto["hasData"][i] else "",
                "tem_dado": str(bool(ponto["hasData"][i])).lower(),
                "parcial": str(bool(ponto.get("isPartial", False))).lower(),
                "coletado_em": hoje,
            })
    nome = f"{consulta['grupo']}_{janela[0]}_{janela[1]}.csv"
    gravar(os.path.join(SAIDA, "series", consulta["grupo"], nome), COLUNAS_SERIE, linhas)


def coletar_mapa(tr, inicio, fim, hoje):
    widgets = tr.explorar([(TERMO_MAPA, "BR")], (inicio, fim))
    linhas = [{
        "grupo": "mapa_uf", "termo": TERMO_MAPA, "geo_pai": "BR",
        "janela_inicio": inicio, "janela_fim": fim,
        "geo_code": g["geoCode"], "geo_nome": g["geoName"],
        "valor": g["value"][0] if g["hasData"][0] else "",
        "tem_dado": str(bool(g["hasData"][0])).lower(), "coletado_em": hoje,
    } for g in tr.mapa(widgets["GEO_MAP"])]
    gravar(os.path.join(SAIDA, "mapa_uf", f"mapa_uf_{inicio}_{fim}.csv"), COLUNAS_MAPA, linhas)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--inicio", default=INICIO_PADRAO, help="domingo inicial (AAAA-MM-DD)")
    p.add_argument("--fim", default=FIM_PADRAO, help="sabado final (AAAA-MM-DD)")
    p.add_argument("--grupo", action="append", help="coletar so este grupo (repetivel)")
    p.add_argument("--sem-mapa", action="store_true", help="nao coletar o mapa por UF")
    p.add_argument("--saida", default=SAIDA, help="pasta de saida (padrao: data/bronze/google_trends)")
    p.add_argument("--janela-dias", type=int, default=DIAS_JANELA,
                   help="forca janelas sobrepostas deste tamanho em vez de uma janela so")
    args = p.parse_args()

    consultas = [c for c in CONSULTAS if not args.grupo or c["grupo"] in args.grupo]
    if not consultas and not args.grupo:
        sys.exit("Nenhuma consulta configurada")
    globals()["SAIDA"] = args.saida
    jans = janelas(args.inicio, args.fim, dias=args.janela_dias) if args.janela_dias != DIAS_JANELA \
        else janelas(args.inicio, args.fim)
    hoje = dt.date.today().isoformat()
    print(f"Janelas: {jans}")

    tr = Trends()
    for c in consultas:
        for j in jans:
            print(f"{c['grupo']} {j[0]} a {j[1]}", flush=True)
            coletar_serie(tr, c, j, hoje)
    if not args.sem_mapa and (not args.grupo or "mapa_uf" in args.grupo):
        print(f"mapa_uf {args.inicio} a {args.fim}", flush=True)
        coletar_mapa(tr, args.inicio, args.fim, hoje)


if __name__ == "__main__":
    main()
