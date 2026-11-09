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
import time

import requests

try:
    import trafilatura
except ImportError:  # roda sem detalhar se a biblioteca não estiver instalada
    trafilatura = None

ENDPOINT = "https://models.github.ai/inference/chat/completions"
MODELOS = [m for m in [os.environ.get("IA_MODELO"), "openai/gpt-4.1-mini", "openai/gpt-4o-mini", "meta/Llama-3.3-70B-Instruct"] if m]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "pt-BR,pt;q=0.9"}
MAX_TEXTO = 9000
INTERVALO = 5      # segundos entre chamadas (limite grátis: ~15 por minuto)
CATEGORIAS = ("Varejo", "Economia", "Mundo")

INSTRUCOES = """Você escreve o resumo de notícias do Bom dia varejo, um portal sobre varejo, atacarejo e economia do consumo.
Com base APENAS no texto da matéria, escreva de 5 a 7 tópicos em português do Brasil, detalhados o bastante para o leitor entender a notícia inteira sem abrir o link:
- o que aconteceu, quem está envolvido, quando e onde;
- TODOS os números importantes (valores, percentuais, datas, prazos, quantidades) exatamente como aparecem no texto;
- regras, condições ou etapas, quando a matéria explicar (ex.: quem tem direito, como funciona, prazos de pagamento);
- o contexto e o que muda a partir de agora, se a matéria disser.
Regras:
- Escreva com suas próprias palavras; não copie frases da matéria.
- Cada tópico com 1 a 3 frases, no máximo 380 caracteres, em tom jornalístico e neutro, sem opinião.
- Ignore legendas de foto, créditos de fotógrafos e agências, chamadas para redes sociais e propagandas.
- Não invente nada que não esteja no texto. Não use frases de efeito. Não inclua seção "Para o varejo".
- Classifique a notícia em uma categoria: Varejo (varejo, atacarejo, supermercados, lojas, indústria de consumo, preço de alimentos), Economia (juros, inflação, câmbio, emprego, salários, impostos, contas públicas no Brasil) ou Mundo (fatos internacionais).
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


_modelo_ok = None
_ultima_chamada = 0.0


def _chamar_ia(token, modelo, titulo, texto):
    global _ultima_chamada
    for _ in range(3):
        espera = INTERVALO - (time.time() - _ultima_chamada)
        if espera > 0:
            time.sleep(espera)
        _ultima_chamada = time.time()
        r = _post_ia(token, modelo, titulo, texto)
        if r.status_code != 429:
            return r
        pausa = min(int(r.headers.get("retry-after", "20") or 20), 65)
        print(f"    … limite por minuto da IA, aguardando {pausa}s")
        time.sleep(pausa)
    return r


def _post_ia(token, modelo, titulo, texto):
    return requests.post(ENDPOINT, timeout=60, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }, json={
        "model": modelo,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": INSTRUCOES},
            {"role": "user", "content": f"Título: {titulo}\n\nTexto da matéria:\n{texto}"},
        ],
    })


def resumir(titulo, texto):
    global _modelo_ok
    token = os.environ.get("IA_TOKEN") or os.environ.get("SITE_TOKEN")
    if not token:
        raise RuntimeError("IA_TOKEN não definido no workflow")
    erros = []
    for modelo in ([_modelo_ok] if _modelo_ok else MODELOS):
        r = _chamar_ia(token, modelo, titulo, texto)
        if r.status_code == 200:
            _modelo_ok = modelo
            break
        erros.append(f"{modelo} → HTTP {r.status_code}: {r.text[:200]}")
        if r.status_code in (401, 403):   # sem permissão: não adianta tentar outro modelo
            break
        if r.status_code == 429:          # limite do dia: os outros modelos dividem a mesma cota
            break
    else:
        raise RuntimeError(" | ".join(erros))
    if r.status_code != 200:
        raise RuntimeError(" | ".join(erros))
    conteudo = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", conteudo, re.S)
    dados = json.loads(m.group(0) if m else conteudo)
    topicos = [t.strip() for t in dados.get("topicos", []) if isinstance(t, str) and len(t.strip()) > 20]
    if len(topicos) < 2:
        return None
    return {"topicos": topicos[:7], "categoria": dados.get("categoria") if dados.get("categoria") in CATEGORIAS else None}


def detalhar(noticia, manter_categoria=False):
    """Troca os tópicos curtos do feed por um resumo detalhado. Devolve True se conseguiu."""
    titulo = noticia["titulo"][:60]
    try:
        try:
            texto = texto_da_materia(noticia["link"])
            if not texto:
                noticia["erro_materia"] = "não achou o texto principal" if trafilatura else "trafilatura não instalado"
        except Exception as e:
            noticia["erro_materia"] = f"{e.__class__.__name__}: {str(e)[:120]}"
            print(f"    · não abriu a matéria ({e.__class__.__name__}); usa o resumo do feed: {titulo}")
            texto = None
        texto = texto or " ".join(noticia.get("topicos", []))
        if len(texto) < 120:
            noticia["erro_ia"] = "texto da matéria não encontrado"
            print(f"    · texto curto demais para resumir: {titulo}")
            return False
        res = resumir(noticia["titulo"], texto)
        if not res:
            print(f"    · IA não devolveu tópicos válidos: {titulo}")
            return False
        noticia["topicos"] = res["topicos"]
        noticia["detalhada"] = True
        noticia.pop("tentativas_ia", None)
        noticia.pop("erro_ia", None)
        if res["categoria"] and not manter_categoria:
            noticia["categoria"] = res["categoria"]
        print(f"    ✓ {len(res['topicos'])} tópicos ({_modelo_ok}): {titulo}")
        return True
    except Exception as e:
        noticia["erro_ia"] = f"{e.__class__.__name__}: {str(e)[:300]}"   # fica salvo para diagnóstico
        print(f"    ✗ IA falhou: {str(e)[:300]}")
        return False
