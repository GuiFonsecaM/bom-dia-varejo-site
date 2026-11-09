"""
Revisa as notícias de hoje e de ontem que entraram pelo coletor sem o resumo detalhado
(ex.: a IA estava fora do ar ou no limite) e tenta de novo, até 3 vezes por notícia.
Também limpa o texto curto do feed (frases cortadas, chamadas e créditos de foto).
Notícias do boletim do WhatsApp não são mexidas.

Rodar à mão:  python redetalhar.py
"""
import json
import os
from datetime import datetime, timedelta

from detalhar import detalhar
from limpeza import texto_limpo, topicos_do_resumo
from publicar_site import TZ, _resumo

AQUI = os.path.dirname(os.path.abspath(__file__))
FONTES_FEED = {f["nome"] for f in json.load(open(os.path.join(AQUI, "fontes.json"), encoding="utf-8"))["feeds"]}
MAX_TENTATIVAS = 3


def revisar_dia(data):
    caminho = os.path.join(AQUI, "data", "dias", f"{data}.json")
    if not os.path.exists(caminho):
        return 0
    dia = json.load(open(caminho, encoding="utf-8"))
    mudou = 0
    for n in dia.get("noticias", []):
        if n.get("detalhada") or n.get("fonte") not in FONTES_FEED or n.get("tentativas_ia", 0) >= MAX_TENTATIVAS:
            continue
        limpos = topicos_do_resumo(texto_limpo(" ".join(n.get("topicos", []))), maximo=6)
        if limpos:
            n["topicos"] = limpos
        if not detalhar(n):
            n["tentativas_ia"] = n.get("tentativas_ia", 0) + 1
        mudou += 1
    if mudou:
        json.dump(dia, open(caminho, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        open(caminho, "a", encoding="utf-8").write("\n")
        atualizar_indice(dia)
    return mudou


def atualizar_indice(dia):
    caminho = os.path.join(AQUI, "data", "indice", f"{dia['data'][:4]}.json")
    if not os.path.exists(caminho):
        return
    indice = json.load(open(caminho, encoding="utf-8"))
    por_titulo = {n["titulo"]: n for n in dia["noticias"]}
    for d in indice.get("dias", []):
        if d["data"] != dia["data"]:
            continue
        for item in d["n"]:
            n = por_titulo.get(item.get("t"))
            if n:
                item["r"] = _resumo(n)
                if n.get("categoria"):
                    item["c"] = n["categoria"]
    json.dump(indice, open(caminho, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(caminho, "a", encoding="utf-8").write("\n")


def main():
    hoje = datetime.now(TZ).date()
    total = sum(revisar_dia((hoje - timedelta(days=i)).isoformat()) for i in range(2))
    print(f"{total} notícias revisadas")


if __name__ == "__main__":
    main()
