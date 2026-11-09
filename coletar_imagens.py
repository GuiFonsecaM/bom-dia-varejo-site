"""
Pega a imagem principal de cada notícia (a mesma da prévia do link: og:image / twitter:image),
reduz e salva em WebP leve dentro do site.

- Tamanho: até 600 px de largura, WebP qualidade 50, sem metadados (~20–30 KB por imagem).
- Fotos com mais de 180 dias são apagadas para o site não passar do limite de 1 GB do GitHub Pages;
  a notícia continua no arquivo, com a arte padrão no lugar da foto.
- Pasta: img/AAAA/MM/<código>.webp
- Olha as notícias de hoje e de ontem que ainda não têm imagem local
  (inclusive as do boletim do WhatsApp). Se a matéria não tiver imagem, marca e não tenta de novo;
  se o site da fonte estiver fora do ar, tenta de novo nas próximas rodadas (até 3 vezes).
- Uma imagem com problema nunca trava o resto: a notícia continua com a arte padrão do site.

Rodar à mão:  python coletar_imagens.py           (grava os arquivos na pasta do site)
              python coletar_imagens.py --dias 7  (olha mais dias para trás)
"""
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageOps

TZ = ZoneInfo("America/Sao_Paulo")
AQUI = os.path.dirname(os.path.abspath(__file__))
LARGURA = 600
QUALIDADE = 50
GUARDAR_DIAS = 180       # fotos mais antigas são apagadas (o texto da notícia fica para sempre)
MIN_LARGURA = 300           # ignora ícones e logos pequenos
MAX_BYTES = 8 * 1024 * 1024
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "pt-BR,pt;q=0.9"}


class _Meta(HTMLParser):
    CHAVES = ("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src")

    def __init__(self):
        super().__init__()
        self.achadas = {}

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            chave = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if chave in self.CHAVES and a.get("content") and chave not in self.achadas:
                self.achadas[chave] = a["content"].strip()
            if chave == "image" and a.get("content"):
                self.achadas.setdefault("itemprop", a["content"].strip())
        elif tag == "link" and a.get("rel", "").lower() == "image_src" and a.get("href"):
            self.achadas.setdefault("image_src", a["href"].strip())

    def melhor(self):
        for c in self.CHAVES + ("itemprop", "image_src"):
            if self.achadas.get(c):
                return self.achadas[c]
        return None


def url_da_imagem(link):
    r = requests.get(link, headers=UA, timeout=20, stream=True)
    r.raise_for_status()
    html_bytes = r.raw.read(1_500_000, decode_content=True)   # a meta tag fica no começo da página
    p = _Meta()
    p.feed(html_bytes.decode(r.encoding or "utf-8", errors="ignore"))
    u = p.melhor()
    return urljoin(r.url, u) if u else None


def baixar_otimizar(url_img, destino):
    r = requests.get(url_img, headers=UA, timeout=25, stream=True)
    r.raise_for_status()
    dados = r.raw.read(MAX_BYTES + 1, decode_content=True)
    if len(dados) > MAX_BYTES:
        raise ValueError("imagem grande demais")
    img = Image.open(io.BytesIO(dados))
    img = ImageOps.exif_transpose(img)
    if img.width < MIN_LARGURA:
        raise ValueError(f"imagem pequena ({img.width}px)")
    if img.mode not in ("RGB", "L"):
        fundo = Image.new("RGB", img.size, (12, 12, 12))
        img = img.convert("RGBA")
        fundo.paste(img, mask=img.split()[-1])
        img = fundo
    if img.width > LARGURA:
        img = img.resize((LARGURA, round(img.height * LARGURA / img.width)), Image.LANCZOS)
    # imagens muito altas (retrato) viram 4:3 centralizado, para não pesar à toa
    if img.height > img.width * 0.75 * 1.6:
        h = round(img.width * 0.75)
        topo = (img.height - h) // 2
        img = img.crop((0, topo, img.width, topo + h))
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    img.convert("RGB").save(destino, "WEBP", quality=QUALIDADE, method=6)
    return os.path.getsize(destino)


def processar_dia(data):
    caminho = os.path.join(AQUI, "data", "dias", f"{data}.json")
    if not os.path.exists(caminho):
        return 0
    dia = json.load(open(caminho, encoding="utf-8"))
    mudou = 0
    for n in dia.get("noticias", []):
        atual = n.get("imagem", "")
        if (atual and not atual.startswith("http")) or n.get("sem_imagem") or not n.get("link"):
            continue
        codigo = hashlib.sha1(n["link"].encode()).hexdigest()[:12]
        relativo = f"img/{data[:4]}/{data[5:7]}/{codigo}.webp"
        destino = os.path.join(AQUI, relativo)
        try:
            if not os.path.exists(destino):
                origem = atual or url_da_imagem(n["link"])
                if not origem:
                    raise ValueError("matéria sem imagem principal")
                kb = baixar_otimizar(origem, destino) / 1024
                print(f"  ✓ {kb:.0f} KB  {n['titulo'][:70]}")
            n["imagem"] = relativo
        except Exception as e:
            n.pop("imagem", None)
            definitivo = isinstance(e, (ValueError, Image.UnidentifiedImageError)) or (
                isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code in (403, 404, 410))
            n["tentativas_imagem"] = n.get("tentativas_imagem", 0) + 1
            if definitivo or n["tentativas_imagem"] >= 3:
                n["sem_imagem"] = True
                n.pop("tentativas_imagem", None)
            motivo = str(e) if definitivo else f"{e.__class__.__name__} (tenta de novo na próxima rodada)"
            print(f"  ✗ {n['titulo'][:70]} — {motivo}")
        mudou += 1
    if mudou:
        json.dump(dia, open(caminho, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        open(caminho, "a", encoding="utf-8").write("\n")
        atualizar_indice(dia)
    return mudou


def atualizar_indice(dia):
    """Leva o caminho da imagem para o índice do ano (usado nas miniaturas da busca)."""
    caminho = os.path.join(AQUI, "data", "indice", f"{dia['data'][:4]}.json")
    if not os.path.exists(caminho):
        return
    indice = json.load(open(caminho, encoding="utf-8"))
    imagens = {n["titulo"]: n.get("imagem") for n in dia["noticias"]}
    for d in indice.get("dias", []):
        if d["data"] == dia["data"]:
            for item in d["n"]:
                img = imagens.get(item.get("t"))
                if img and not img.startswith("http"):
                    item["i"] = img
    json.dump(indice, open(caminho, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(caminho, "a", encoding="utf-8").write("\n")


def limpar_antigas():
    limite = datetime.now(TZ).date() - timedelta(days=GUARDAR_DIAS)
    removidas = 0
    pasta = os.path.join(AQUI, "img")
    for raiz, _, arquivos in os.walk(pasta):
        partes = os.path.relpath(raiz, pasta).split(os.sep)
        if len(partes) != 2 or not all(x.isdigit() for x in partes):
            continue
        ano, mes = map(int, partes)
        ultimo_dia_do_mes = (datetime(ano + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1)).date()
        if ultimo_dia_do_mes < limite:
            for a in arquivos:
                os.remove(os.path.join(raiz, a))
                removidas += 1
            try:
                os.rmdir(raiz)
            except OSError:
                pass
    if removidas:
        print(f"{removidas} fotos com mais de {GUARDAR_DIAS} dias apagadas")


def main():
    dias = int(sys.argv[sys.argv.index("--dias") + 1]) if "--dias" in sys.argv else 2
    hoje = datetime.now(TZ).date()
    total = 0
    for i in range(dias):
        data = (hoje - timedelta(days=i)).isoformat()
        print(f"{data}:")
        total += processar_dia(data)
    print(f"\n{total} notícias atualizadas")
    limpar_antigas()


if __name__ == "__main__":
    main()
