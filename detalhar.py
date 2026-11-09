"""
Escreve um resumo detalhado de cada notícia coletada, nas próprias palavras, em tópicos.

1. Abre a matéria original e extrai o texto principal (trafilatura).
2. Pede a uma IA gratuita de 5 a 7 tópicos detalhados em português: o que aconteceu, números, quem, quando, impacto.
   - Google Gemini (principal): chave grátis em https://aistudio.google.com/apikey → secret GEMINI_API_KEY
   - Groq (reserva, opcional):  chave grátis em https://console.groq.com/keys     → secret GROQ_API_KEY
   O modelo é escolhido sozinho na lista de modelos disponíveis da chave (sem nome fixo que pode sair do ar).
3. Se algo falhar (site bloqueado, sem texto, IA fora do ar ou limite atingido),
   a notícia continua com o resumo curto do feed e a revisão tenta de novo depois. Nada trava a coleta.

Variáveis de ambiente opcionais: GEMINI_MODELO, GROQ_MODELO (forçar um modelo específico).
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

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "pt-BR,pt;q=0.9"}
MAX_TEXTO = 9000
CATEGORIAS = ("Varejo", "Economia", "Política", "Mundo")

PROVEDORES = [
    {   # Google Gemini — API compatível com OpenAI
        "nome": "Gemini", "chave": "GEMINI_API_KEY", "forcar": "GEMINI_MODELO",
        "base": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "preferencias": [r"gemini-[\d.]+-flash-lite$", r"gemini-[\d.]+-flash$", r"gemini-[\d.]+-flash-lite", r"gemini-[\d.]+-flash"],
        "evitar": r"image|tts|audio|live|embed|vision|thinking|exp",
        "intervalo": 5, "max_texto": 9000,
    },
    {   # Groq — limite de tokens por minuto menor, por isso espera mais entre pedidos e manda menos texto
        "nome": "Groq", "chave": "GROQ_API_KEY", "forcar": "GROQ_MODELO",
        "base": "https://api.groq.com/openai/v1/",
        "preferencias": [r"^openai/gpt-oss-120b$", r"llama-3\.3-70b", r"^openai/gpt-oss", r"qwen", r"llama"],
        "evitar": r"guard|whisper|tts|vision|compound|prompt",
        "intervalo": 22, "max_texto": 5000,
    },
]

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
- Classifique a notícia em uma categoria: Varejo (varejo, atacarejo, supermercados, lojas, indústria de consumo, preço de alimentos), Economia (juros, inflação, câmbio, emprego, salários, impostos, contas públicas no Brasil), Política (governo, Congresso, Judiciário, eleições e partidos no Brasil) ou Mundo (fatos internacionais).
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


# ---------------------------------------------------------------- provedores de IA

_estado = {}          # por provedor: modelo escolhido, última chamada, se esgotou
_ultimo_modelo = None


def _cabecalho(p):
    return {"Authorization": f"Bearer {os.environ[p['chave']]}", "Content-Type": "application/json"}


def _escolher_modelo(p):
    if os.environ.get(p["forcar"]):
        return os.environ[p["forcar"]]
    r = requests.get(p["base"] + "models", headers=_cabecalho(p), timeout=20)
    r.raise_for_status()
    ids = [m["id"].removeprefix("models/") for m in r.json().get("data", [])]
    ids = [i for i in ids if not re.search(p["evitar"], i)]

    def versao(i):
        n = re.findall(r"\d+(?:\.\d+)?", i)
        return float(n[0]) if n else 0

    for padrao in p["preferencias"]:
        achados = sorted((i for i in ids if re.search(padrao, i) and "preview" not in i), key=versao, reverse=True) \
            or sorted((i for i in ids if re.search(padrao, i)), key=versao, reverse=True)
        if achados:
            return achados[0]
    raise RuntimeError(f"nenhum modelo de texto encontrado na conta ({len(ids)} modelos listados)")


def _pedir(p, titulo, texto):
    est = _estado.setdefault(p["nome"], {"ultima": 0.0})
    if "modelo" not in est:
        est["modelo"] = _escolher_modelo(p)
        print(f"    · IA: {p['nome']} / {est['modelo']}")
    corpo = {
        "model": est["modelo"],
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": INSTRUCOES},
            {"role": "user", "content": f"Título: {titulo}\n\nTexto da matéria:\n{texto[:p['max_texto']]}"},
        ],
    }
    for tentativa in range(3):
        espera = p["intervalo"] - (time.time() - est["ultima"])
        if espera > 0:
            time.sleep(espera)
        est["ultima"] = time.time()
        r = requests.post(p["base"] + "chat/completions", headers=_cabecalho(p), json=corpo, timeout=90)
        if r.status_code != 429:
            return r
        texto_erro = r.text.lower()
        if "per day" in texto_erro or "perday" in texto_erro or "daily" in texto_erro or tentativa == 2:
            return r                                   # limite do dia: não adianta esperar
        pausa = min(int(float(r.headers.get("retry-after", "30") or 30)), 70)
        print(f"    … limite por minuto do {p['nome']}, aguardando {pausa}s")
        time.sleep(pausa)
    return r


def resumir(titulo, texto):
    global _ultimo_modelo
    disponiveis = [p for p in PROVEDORES if os.environ.get(p["chave"])]
    if not disponiveis:
        raise RuntimeError("nenhuma chave de IA configurada (crie o secret GEMINI_API_KEY no GitHub)")
    erros = []
    for p in disponiveis:
        est = _estado.get(p["nome"], {})
        if est.get("esgotado"):
            erros.append(f"{p['nome']}: {est['esgotado']}")
            continue
        try:
            r = _pedir(p, titulo, texto)
        except Exception as e:
            erros.append(f"{p['nome']}: {e.__class__.__name__} {str(e)[:150]}")
            continue
        if r.status_code != 200:
            msg = f"HTTP {r.status_code}: {r.text[:200]}"
            erros.append(f"{p['nome']} → {msg}")
            if r.status_code in (401, 403, 429):     # chave inválida ou cota do dia: pula este provedor no resto da rodada
                _estado.setdefault(p["nome"], {})["esgotado"] = msg
            continue
        try:
            conteudo = r.json()["choices"][0]["message"]["content"] or ""
            m = re.search(r"\{.*\}", conteudo, re.S)
            dados = json.loads(m.group(0) if m else conteudo)
        except Exception:
            erros.append(f"{p['nome']}: resposta fora do formato: {r.text[:150]}")
            continue
        topicos = [t.strip() for t in dados.get("topicos", []) if isinstance(t, str) and len(t.strip()) > 20]
        if len(topicos) < 2:
            erros.append(f"{p['nome']}: menos de 2 tópicos")
            continue
        _ultimo_modelo = f"{p['nome']}/{_estado[p['nome']]['modelo']}"
        cat = dados.get("categoria")
        return {"topicos": topicos[:7], "categoria": cat if cat in CATEGORIAS else None}
    raise RuntimeError(" | ".join(erros))


def detalhar(noticia, manter_categoria=False):
    """Troca os tópicos curtos do feed por um resumo detalhado. Devolve True se conseguiu."""
    titulo = noticia["titulo"][:60]
    try:
        try:
            texto = texto_da_materia(noticia["link"])
            if not texto:
                noticia["erro_materia"] = "não achou o texto principal" if trafilatura else "trafilatura não instalado"
            else:
                noticia.pop("erro_materia", None)
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
        noticia["topicos"] = res["topicos"]
        noticia["detalhada"] = True
        noticia.pop("tentativas_ia", None)
        noticia.pop("erro_ia", None)
        if res["categoria"] and not manter_categoria:
            noticia["categoria"] = res["categoria"]
        print(f"    ✓ {len(res['topicos'])} tópicos ({_ultimo_modelo}): {titulo}")
        return True
    except Exception as e:
        noticia["erro_ia"] = f"{e.__class__.__name__}: {str(e)[:300]}"   # fica salvo para diagnóstico
        print(f"    ✗ IA falhou: {str(e)[:300]}")
        return False
