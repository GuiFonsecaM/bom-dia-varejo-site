"""
Verifica se surgiram notícias novas e acrescenta no site (roda 3x por dia pelo GitHub Actions).

- Lê os feeds de fontes.json.
- Fica só com notícias das últimas `janela_horas` que falam de varejo/atacarejo/economia do consumo.
- Ignora o que já está no site (inclusive o que veio do boletim do WhatsApp): mesmo link
  ou título muito parecido, olhando os últimos 7 dias.
- Publica no máximo `maximo_por_rodada` notícias por vez, com o link original.
- Abre cada matéria e escreve um resumo detalhado em tópicos (detalhar.py).

Rodar à mão:  python coletar_noticias.py            (publica)
              python coletar_noticias.py --teste    (só mostra o que publicaria)
"""
import calendar
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests

from detalhar import detalhar
from publicar_site import TZ, chave_link, ja_existe, publicar_no_site

AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.path.join(AQUI, "fontes.json"), encoding="utf-8"))
UA = {"User-Agent": "Mozilla/5.0 (compatible; BomDiaVarejoBot/1.0)"}


def texto_limpo(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    # rodapés comuns de WordPress ("O post ... apareceu primeiro em ...")
    s = re.split(r"\b(O post|The post)\b.*?(apareceu primeiro em|appeared first on)", s)[0].strip()
    s = re.sub(r"\s*(\[…\]|\[\.\.\.\]|Leia mais.*|Continue lendo.*)$", "", s, flags=re.I).strip()
    return s


def link_original(url):
    """Remove parâmetros de rastreio (utm_*, etc.) mantendo o link da matéria."""
    u = urlsplit((url or "").strip())
    q = [(k, v) for k, v in parse_qsl(u.query) if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref"))]
    return urlunsplit((u.scheme, u.netloc, u.path, urlencode(q), ""))


def topicos_do_resumo(resumo, maximo=3):
    frases = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9\"“])", resumo)
    out = []
    for f in frases:
        f = f.strip()
        if len(f) < 25:
            continue
        out.append(f if len(f) <= 320 else f[:319].rsplit(" ", 1)[0] + "…")
        if len(out) == maximo:
            break
    return out


def relevancia(texto, todas):
    t = texto.lower()
    acertos = sum(1 for p in CONFIG["palavras_chave"] if re.search(r"\b" + re.escape(p.lower()) + r"\b", t))
    return acertos + (1 if todas else 0)


def categoria(texto):
    t = texto.lower()
    for nome, palavras in CONFIG.get("categorias", {}).items():
        if any(p.lower() in t for p in palavras):
            return nome
    return CONFIG.get("categoria_padrao", "Varejo")


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
            resumo = texto_limpo(e.get("summary") or e.get("description"))
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
                    "topicos": topicos_do_resumo(resumo) or ([resumo] if resumo else []),
                    "fonte": feed["nome"],
                    "link": link,
                    "categoria": categoria(f"{titulo} {resumo}"),
                },
            })
    return candidatas


def main():
    teste = "--teste" in sys.argv
    vistos = existentes_no_site()
    candidatas = sorted(coletar(), key=lambda c: (c["nota"], c["quando"]), reverse=True)

    novas = []
    for c in candidatas:
        n = c["noticia"]
        if ja_existe(n, vistos):
            continue
        novas.append(n)
        vistos.append((chave_link(n["link"]), n["titulo"]))
        if len(novas) >= CONFIG.get("maximo_por_rodada", 6):
            break

    print(f"\n{len(candidatas)} candidatas, {len(novas)} novas")
    for n in novas:
        print(f"  • [{n['categoria']}] {n['titulo']} — {n['fonte']}")

    if novas:
        print("\nDetalhando as notícias:")
        for n in novas:
            detalhar(n)

    if novas and not teste:
        publicar_no_site(novas)


if __name__ == "__main__":
    main()
