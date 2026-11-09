"""Limpa o resumo que vem nos feeds (RSS), para nunca publicar texto cortado ou com sujeira."""
import html
import re
import unicodedata

# Frases de "chamada" que os portais colocam no meio do resumo
LIXO = [
    r"📱?\s*Favorite o g1 no Google[^.!?]*?(?:principais notícias do dia|$)",
    r"📲?\s*(?:Siga|Participe do canal|Entre no canal)[^.!?]*?(?:WhatsApp|Telegram|Instagram)[^.!?]*",
    r"(?:Leia também|LEIA TAMBÉM|Leia mais|Saiba mais|Veja também|Assista)\s*:?[^.!?]*$",
    r"(?:Clique aqui|Inscreva-se)[^.!?]*",
    r"\b(O post|The post)\b.*?(apareceu primeiro em|appeared first on).*$",
    r"\[…\]|\[\.\.\.\]",
]
AGENCIAS = (r"REUTERS|Reuters|AFP|AP Photo|AP|EFE|BBC|Getty Images|Images|Bloomberg|Folhapress|Estadão Conteúdo|Estadão|"
            r"Agência Brasil|Agência Senado|Agência Câmara|Agência O Globo|O Globo|TV Globo|Globo|g1|Divulgação|Reprodução|"
            r"Arquivo pessoal|Arquivo|Freepik|Unsplash|Shutterstock|Pexels|iStock|Canva|Pixabay|Wikimedia Commons")
NOME = r"[A-ZÀ-Ý][\wÀ-ÿ.'’-]*"
# "Getty Images/BBC", "Images/BBC", "Umit Bektas/Reuters", "Marcello Casal Jr/Agência Brasil", "Divulgação/Renault"
CREDITO_BARRA = rf"(?:{NOME}\s){{0,3}}{NOME}\s?/\s?(?:{AGENCIAS}|{NOME})(?:\s?/\s?{NOME})*"
# crédito solto: "REUTERS via BBC", "Divulgação", "Reprodução"
CREDITO_SOLTO = rf"(?:{AGENCIAS})(?:\s+via\s+{NOME})?"
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿️]")


def _palavras(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]{3,}", t)


def _repete_titulo(frase, titulo):
    """True se a frase é só a legenda/título repetido (com ou sem crédito do fotógrafo no fim)."""
    pf, pt = _palavras(frase), set(_palavras(titulo))
    if not pf or not pt:
        return False
    dentro = sum(1 for p in pf if p in pt)
    return dentro / len(pf) >= 0.6


def texto_limpo(s, titulo=None):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = EMOJI.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for padrao in LIXO:
        s = re.sub(padrao, " ", s, flags=re.I)
    # legenda da foto + crédito com barra no começo ("Donald Trump em 2 de novembro Umit Bektas/Reuters O presidente...")
    m = re.search(rf"(?<![\wÀ-ÿ]){CREDITO_BARRA}\s+(?=[A-ZÀ-Ý\"“])", s[:260])
    if m:
        s = s[m.end():]
    # créditos com barra que sobrarem no meio do texto
    s = re.sub(rf"(?<![\wÀ-ÿ]){CREDITO_BARRA}(?=\s+[A-ZÀ-Ý\"“]|\s*$)", " ", s)
    # legenda + crédito solto no começo ("... 'suave' REUTERS via BBC Não há ...")
    m = re.match(rf"^(.{{0,180}}?)\s?\b{CREDITO_SOLTO}\s+(?=[A-ZÀ-Ý\"“])", s)
    if m:
        s = s[m.end():]
    s = re.sub(r"\s+", " ", s).strip()
    # g1: o resumo começa repetindo o título (legenda da foto) — corta essa parte
    if titulo:
        frases = re.split(r"(?<=[.!?])\s+", s)
        while frases and _repete_titulo(frases[0], titulo):
            frases.pop(0)
        s = " ".join(frases)
    return s


def topicos_do_resumo(resumo, maximo=3, titulo=None):
    """Divide em frases completas. Frase cortada (termina em … ou ...), citação aberta ou repetição do título fica de fora."""
    frases = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9\"“])", resumo or "")
    out = []
    for f in frases:
        f = f.strip()
        if len(f) < 25 or f.endswith(("…", "...")) or not f.endswith((".", "!", "?", "\"", "”", ")")):
            continue
        if f.count("\"") % 2 or f.count("“") != f.count("”"):
            continue
        if titulo and _repete_titulo(f, titulo):
            continue
        out.append(f if len(f) <= 320 else f[:319].rsplit(" ", 1)[0] + "…")
        if len(out) == maximo:
            break
    return out
