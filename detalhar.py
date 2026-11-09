"""
Escreve um resumo detalhado de cada notícia coletada, nas próprias palavras, em tópicos.

1. Abre a matéria original e extrai o texto principal (trafilatura).
2. Pede à IA do GitHub (GitHub Models, grátis dentro do GitHub Actions com o GITHUB_TOKEN)
   de 4 a 6 tópicos detalhados em português: o que aconteceu, números, quem, quando, impacto.
3. Se algo falhar (site bloqueado, sem texto, IA fora do ar ou limite atingido),
   a notícia continua com o resumo curto do feed. Nada trava a coleta.

Variáveis de ambiente:
    IA_TOKEN    token com acesso a GitHub Models (no Actions: secrets.GITHUB_TOKEN + permissão models: read)
    IA_MODELO   opcional, padrão "openai/gpt-4.1-mini"
"""
import json
import os
import re

import requests

try:
    import trafilatura
except ImportError:  # roda sem detalhar se a biblioteca não estiver instalada
    trafilatura = None

ENDPOINT = "https://models.github.ai/inference/chat/completions"
MODELO = os.environ.get("IA_MODELO", "openai/gpt-4.1-mini")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "pt-BR,pt;q=0.9"}
MAX_TEXTO = 7000
CATEGORIAS = ("Varejo", "Atacarejo", "Economia")

INSTRUCOES = """Você escreve o resumo de notícias do Bom dia varejo, um portal sobre varejo, atacarejo e economia do consumo.
Com base APENAS no texto da matéria, escreva de 4 a 6 tópicos em português do Brasil que permitam entender a notícia sem abrir o link:
- o que aconteceu, quem está envolvido, quando e onde;
- os números importantes (valores, percentuais, datas, quantidades) exatamente como aparecem no texto;
- o contexto e o que muda a partir de agora, se a matéria disser.
Regras:
- Escreva com suas próprias palavras; não copie frases da matéria.
- Cada tópico com 1 ou 2 frases curtas, no máximo 300 caracteres, em tom jornalístico e neutro, sem opinião.
- Não invente nada que não esteja no texto. Não use frases de efeito. Não inclua seção "Para o varejo".
- Classifique a notícia em uma categoria: Varejo, Atacarejo ou Economia.
Responda só com JSON no formato: {"topicos": ["...", "..."], "categoria": "..."}"""


def texto_da_materia(link):
    if not trafilatura:
        return None
    r = requests.get(link, headers=UA, timeout=20)
    r.raise_for_status()
    texto = trafilatura.extract(r.content, include_comments=False, include_tables=False, favor_precision=True)
    if not texto or len(texto) < 400:
        return None
    return texto[:MAX_TEXTO]


def resumir(titulo, texto):
    token = os.environ.get("IA_TOKEN") or os.environ.get("SITE_TOKEN")
    if not token:
        return None
    r = requests.post(ENDPOINT, timeout=60, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    }, json={
        "model": MODELO,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": INSTRUCOES},
            {"role": "user", "content": f"Título: {titulo}\n\nTexto da matéria:\n{texto}"},
        ],
    })
    if r.status_code == 429:
        raise RuntimeError("limite da IA atingido")
    r.raise_for_status()
    conteudo = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", conteudo, re.S)
    dados = json.loads(m.group(0) if m else conteudo)
    topicos = [t.strip() for t in dados.get("topicos", []) if isinstance(t, str) and len(t.strip()) > 20]
    if len(topicos) < 2:
        return None
    return {"topicos": topicos[:6], "categoria": dados.get("categoria") if dados.get("categoria") in CATEGORIAS else None}


def detalhar(noticia):
    """Troca os tópicos curtos do feed por um resumo detalhado. Devolve True se conseguiu."""
    try:
        texto = texto_da_materia(noticia["link"])
        if not texto:
            print(f"    · sem texto aproveitável, mantém resumo do feed: {noticia['titulo'][:60]}")
            return False
        res = resumir(noticia["titulo"], texto)
        if not res:
            print(f"    · IA indisponível, mantém resumo do feed: {noticia['titulo'][:60]}")
            return False
        noticia["topicos"] = res["topicos"]
        if res["categoria"]:
            noticia["categoria"] = res["categoria"]
        print(f"    ✓ {len(res['topicos'])} tópicos: {noticia['titulo'][:60]}")
        return True
    except Exception as e:
        print(f"    · {e.__class__.__name__}: {str(e)[:80]} — mantém resumo do feed")
        return False
