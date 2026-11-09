"""Limpa o resumo que vem nos feeds (RSS), para nunca publicar texto cortado ou com sujeira."""
import html
import re

# Frases de "chamada" que os portais colocam no meio do resumo
LIXO = [
    r"📱?\s*Favorite o g1 no Google[^.!?]*?(?:principais notícias do dia|$)",
    r"📲?\s*(?:Siga|Participe do canal|Entre no canal)[^.!?]*?(?:WhatsApp|Telegram|Instagram)[^.!?]*",
    r"(?:Leia também|LEIA TAMBÉM|Leia mais|Saiba mais|Veja também|Assista)\s*:?[^.!?]*$",
    r"(?:Clique aqui|Inscreva-se)[^.!?]*",
    r"\b(O post|The post)\b.*?(apareceu primeiro em|appeared first on).*$",
    r"\[…\]|\[\.\.\.\]",
]
# Crédito de foto que aparece colado à legenda no começo do resumo (ex.: "... 'suave' REUTERS via BBC Não há...")
CREDITO = (r"(?:REUTERS|Reuters|AFP|AP Photo|AP|EFE|Getty Images|Divulgação|Reprodução|Arquivo pessoal|"
           r"Agência Brasil|Agência Senado|Agência Câmara|Freepik|Unsplash|TV Globo|g1|Shutterstock)"
           r"(?:\s*/\s*[\wÀ-ÿ]+)*(?:\s+via\s+[\wÀ-ÿ]+)?")
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿️]")


def texto_limpo(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = EMOJI.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for padrao in LIXO:
        s = re.sub(padrao, " ", s, flags=re.I)
    # legenda + crédito no começo: descarta tudo até o crédito
    m = re.match(r"^(.{10,180}?)\s" + CREDITO + r"\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ\"“])", s)
    if m:
        s = s[m.end():]
    return re.sub(r"\s+", " ", s).strip()


def topicos_do_resumo(resumo, maximo=3):
    """Divide em frases completas. Frase cortada (termina em … ou ...) ou citação aberta fica de fora."""
    frases = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9\"“])", resumo or "")
    out = []
    for f in frases:
        f = f.strip()
        if len(f) < 25 or f.endswith(("…", "...")) or not f.endswith((".", "!", "?", "\"", "”", ")")):
            continue
        if f.count("\"") % 2 or f.count("“") != f.count("”"):
            continue
        out.append(f if len(f) <= 320 else f[:319].rsplit(" ", 1)[0] + "…")
        if len(out) == maximo:
            break
    return out
