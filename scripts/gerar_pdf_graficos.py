"""
Junta os graficos estaticos da analise num PDF unico (A4 paisagem), com capa e
legenda, como copia de seguranca para a apresentacao. Nao depende do Grafana
nem da AWS: usa os PNGs gerados por analise_hipoteses.py e analise_destinos.py.

Entrada: graficos/cruzamento/*.png, graficos/comparacao_destinos/*.png,
         data/gold/cruzamento_semanal_br (periodo e totais da capa)
Saida:   graficos/graficos_analise.pdf

Uso (depois de rodar o pipeline e as duas analises):
  python scripts/gerar_pdf_graficos.py
"""
import datetime as dt
import glob
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
GRAFICOS = os.path.join(BASE_DIR, "graficos")
SAIDA = os.path.join(GRAFICOS, "graficos_analise.pdf")
GOLD_BR = os.path.join(BASE_DIR, "data", "gold", "cruzamento_semanal_br", "cruzamento_semanal_br_parte0001.csv")

TINTA, TINTA2, MUDO = "#0b0b0b", "#52514e", "#898781"
A4 = (11.69, 8.27)

SECOES = [
    ("cruzamento", "Voos para EUA, Canadá e Reino Unido × busca por inglês"),
    ("comparacao_destinos", "Férias ou destino? Grupo de comparação"),
]
LEGENDAS = {
    "01_series_semanais": "Passageiros e busca na mesma base (100 = maior semana). Faixas: férias escolares.",
    "02_correlograma_cruzado": "Correlação por defasagem. Positivo: a busca vem depois do voo. Vazado: p < 0,05 pelo tamanho efetivo.",
    "03_dispersao_defasagem3": "Cada ponto é uma semana: passageiros na semana t e busca três semanas depois.",
    "04_mapa_correlacoes": "Todas as séries de voos × todos os termos, na mesma semana.",
    "05_regional_sp_rj_mg": "Voos com embarque na UF × busca na UF. Guarulhos (SP) é hub nacional.",
    "06_interesse_por_uf": "Interesse relativo por curso de inglês e participação de cada UF nos embarques.",
    "07_ano_a_ano": "Sobreposição por semana do ano: picos alinhados indicam sazonalidade.",
    "08_perfil_temporada": "Cada série nas férias, na volta às aulas e no período letivo.",
    "01_segmentos_x_busca": "Cada grupo de destino × busca. A Europa, que não segue as férias, é o contraste.",
    "02_correlograma_por_destino": "Voos de férias para qualquer destino antecedem a busca; Europa não.",
    "03_parciais": "O que cada grupo de destino explica além do outro.",
    "04_volume_x_composicao": "Quanto se viaja importa; a fatia que vai para países anglófonos, não.",
    "05_perfil_temporada_destinos": "Passageiros por temporada escolar, por destino.",
}


def pagina_texto(pdf, titulo, linhas, tamanho=26):
    fig = plt.figure(figsize=A4)
    fig.text(0.07, 0.80, titulo, fontsize=tamanho, fontweight="bold", color=TINTA, va="top", wrap=True)
    for i, l in enumerate(linhas):
        fig.text(0.07, 0.62 - i * 0.055, l, fontsize=13, color=TINTA2, va="top")
    pdf.savefig(fig)
    plt.close(fig)


def pagina_grafico(pdf, caminho, secao, n, total):
    nome = os.path.splitext(os.path.basename(caminho))[0]
    img = mpimg.imread(caminho)
    fig = plt.figure(figsize=A4)
    fig.text(0.04, 0.965, secao, fontsize=10, color=MUDO, va="top")
    fig.text(0.96, 0.965, f"{n}/{total}", fontsize=10, color=MUDO, va="top", ha="right")
    ax = fig.add_axes([0.04, 0.10, 0.92, 0.83])
    ax.imshow(img)
    ax.axis("off")
    fig.text(0.04, 0.05, LEGENDAS.get(nome, nome), fontsize=11, color=TINTA2, va="center")
    pdf.savefig(fig)
    plt.close(fig)


def main():
    br = pd.read_csv(GOLD_BR, sep=";")
    c = br[br.semana_completa]
    capa = [
        f"Semanas completas: {len(c)} ({c.semana_inicio.min()} a {c.semana_fim.max()})",
        f"Voos comerciais: {c.qtd_voos.sum():,}   Passageiros: {c.nr_passageiros.sum():,}".replace(",", "."),
        "Fontes: ANAC (Dados Estatísticos do Transporte Aéreo, etapas combinadas) e Google Trends",
        f"Gerado em {dt.date.today().strftime('%d/%m/%Y')} a partir das tabelas gold",
        "Projeto Integrador, grupo 4: Boost Your English",
    ]
    paginas = [(sec, titulo, sorted(glob.glob(os.path.join(GRAFICOS, sec, "*.png")))) for sec, titulo in SECOES]
    total = sum(len(p) for _, _, p in paginas)
    if not total:
        raise SystemExit("Nenhum PNG em graficos/. Rode analise_hipoteses.py e analise_destinos.py antes.")

    with PdfPages(SAIDA) as pdf:
        pagina_texto(pdf, "Voos para países anglófonos × intenção de estudar inglês", capa)
        n = 0
        for _, titulo, arquivos in paginas:
            for a in arquivos:
                n += 1
                pagina_grafico(pdf, a, titulo, n, total)
        info = pdf.infodict()
        info["Title"] = "Voos para países anglófonos × intenção de estudar inglês"
        info["Author"] = "Grupo 4"
    print(f"Gravado: {os.path.relpath(SAIDA, BASE_DIR)} ({total} gráficos + capa)")


if __name__ == "__main__":
    main()
