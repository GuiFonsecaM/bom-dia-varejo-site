"""
Verifica se surgiram notícias novas e acrescenta no site (roda 3x por dia pelo GitHub Actions).

- Lê os feeds de fontes.json.
- Fica só com notícias das últimas `janela_horas` que falam de varejo/atacarejo/economia do consumo.
- Ignora o que já está no site (inclusive o que veio do boletim do WhatsApp): mesmo link
  ou título muito parecido, olhando os últimos 7 dias.
- Publica no máximo `maximo_por_categoria` notícias de cada categoria por rodada (padrão: 5).
- Varejo alimentar tem prioridade: cada palavra-chave do setor vale 3 pontos na relevância.
- Abre cada matéria e escreve um resumo detalhado em tópicos (detalhar.py).

Rodar à mão:  python coletar_noticias.py            (publica)
              python coletar_noticias.py --teste    (só mostra o que publicaria)
"""
import calendar
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests

from detalhar import detalhar
from limpeza import texto_limpo, topicos_do_resumo
from publicar_site import TZ, chave_link, ja_existe, publicar_no_site

AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.path.join(AQUI, "fontes.json"), encoding="utf-8"))
UA = {"User-Agent": "Mozilla/5.0 (compatible; BomDiaVarejoBot/1.0)"}


def link_original(url):
    """Remove parâmetros de rastreio (utm_*, etc.) mantendo o link da matéria."""
    u = urlsplit((url or "").strip())
    q = [(k, v) for k, v in parse_qsl(u.query) if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref"))]
    return urlunsplit((u.scheme, u.netloc, u.path, urlencode(q), ""))


def _conta(palavras, t):
    return sum(1 for p in palavras if re.search(r"(?<![\w])" + re.escape(p.lower()) + r"(?![\w])", t))


def relevancia(texto, todas):
    """Varejo alimentar vale 3 pontos por palavra; os demais temas, 1 ponto."""
    t = texto.lower()
    return (3 * _conta(CONFIG.get("palavras_chave_varejo_alimentar", []), t)
            + _conta(CONFIG["palavras_chave"], t) + (1 if todas else 0))


def categoria(texto, fixa=None, padrao=None):
    if fixa:
        return fixa
    t = texto.lower()
    if _conta(CONFIG.get("palavras_chave_varejo_alimentar", []), t):
        return "Varejo"
    for nome, palavras in CONFIG.get("categorias", {}).items():
        if _conta(palavras, t):
            return nome
    return padrao or CONFIG.get("categoria_padrao", "Varejo")


def data_do_item(e):
    for campo in ("published_parsed", "updated_parsed"):
        tm = e.get(campo)
        if tm:
            return datetime.fromtimestamp(calendar.timegm(tm), tz=timezone.utc)
    return None


def existentes_no_site(dias=7):
    """(link, título) das notícias já publicadas nos últimos dias, lidos do próprio repositório."""
    hoje = datetime.now(TZ).date()
    out = []
    for i in range(dias):
        d = (hoje - timedelta(days=i)).isoformat()
        caminho = os.path.join(AQUI, "data", "dias", f"{d}.json")
        if os.path.exists(caminho):
            for n in json.load(open(caminho, encoding="utf-8")).get("noticias", []):
                out.append((chave_link(n.get("link")), n.get("titulo", "")))
    return out


def coletar():
    limite = datetime.now(timezone.utc) - timedelta(hours=CONFIG.get("janela_horas", 24))
    candidatas = []
    for feed in CONFIG["feeds"]:
        try:
            r = requests.get(feed["url"], headers=UA, timeout=20)
            r.raise_for_status()
            itens = feedparser.parse(r.content).entries
            print(f"✓ {feed['nome']}: {len(itens)} itens no feed")
        except Exception as e:
            print(f"✗ {feed['nome']}: não respondeu ({e.__class__.__name__}) — pulando")
            continue
        for e in itens:
            quando = data_do_item(e)
            if not quando or quando < limite:
                continue
            titulo = texto_limpo(e.get("title"))
            resumo = texto_limpo(e.get("summary") or e.get("description"), titulo)
            link = link_original(e.get("link"))
            if not titulo or not link:
                continue
            nota = relevancia(f"{titulo} {resumo}", feed.get("todas"))
            if nota == 0:
                continue
            candidatas.append({
                "nota": nota, "quando": quando,
                "noticia": {
                    "titulo": titulo,
                    "topicos": topicos_do_resumo(resumo, titulo=titulo),
                    "fonte": feed["nome"],
                    "link": link,
                    "categoria": categoria(f"{titulo} {resumo}", feed.get("categoria"), feed.get("categoria_padrao")),
                },
                "categoria_fixa": bool(feed.get("categoria")),
            })
    return candidatas


def main():
    teste = "--teste" in sys.argv
    vistos = existentes_no_site()
    candidatas = sorted(coletar(), key=lambda c: (c["nota"], c["quando"]), reverse=True)

    limites = CONFIG.get("maximo_por_categoria", {})
    por_categoria, novas, fixas = {}, [], set()
    for c in candidatas:
        n = c["noticia"]
        if ja_existe(n, vistos) or por_categoria.get(n["categoria"], 0) >= limites.get(n["categoria"], 5):
            continue
        novas.append(n)
        if c["categoria_fixa"]:
            fixas.add(id(n))
        por_categoria[n["categoria"]] = por_categoria.get(n["categoria"], 0) + 1
        vistos.append((chave_link(n["link"]), n["titulo"]))

    print(f"\n{len(candidatas)} candidatas, {len(novas)} novas")
    for n in novas:
        print(f"  • [{n['categoria']}] {n['titulo']} — {n['fonte']}")

    if novas:
        print("\nDetalhando as notícias:")
        # a IA grátis tem limite diário: detalha primeiro Varejo, depois Economia, Política e Mundo
        prioridade = {"Varejo": 0, "Economia": 1, "Política": 2, "Mundo": 3}
        for n in sorted(novas, key=lambda x: prioridade.get(x["categoria"], 9)):
            detalhar(n, manter_categoria=id(n) in fixas)

    if novas and not teste:
        publicar_no_site(novas)


if __name__ == "__main__":
    main()
