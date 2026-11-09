"""
Atualiza os indicadores do site (aba "Indicadores") a cada rodada do workflow.

Fontes gratuitas, sem chave:
- Banco Central (SGS): Selic, CDI, IPCA, IGP-M, desemprego
- AwesomeAPI: dólar e euro comercial
- Yahoo Finance (gráfico diário): Ibovespa, bolsas, petróleo, ouro, commodities, juros dos EUA, bitcoin

Grava data/indicadores.json com valor, variação, data de referência e um histórico curto (para o minigráfico).
Se uma fonte falhar, mantém o último valor conhecido e marca como desatualizado — nunca apaga o indicador.

Rodar à mão:  python coletar_indicadores.py
"""
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("America/Sao_Paulo")
AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(AQUI, "data", "indicadores.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
PONTOS = 30  # pontos do minigráfico

# formato: pct | brl | usd | pts | num     variacao: pct (variação %) | pp (pontos percentuais)
SECOES = [
    {"nome": "Brasil", "grupos": [
        {"nome": "Juros e inflação", "itens": [
            {"id": "selic", "nome": "Selic (meta)", "fonte": "sgs", "codigo": 432, "n": 400, "formato": "pct", "casas": 2, "variacao": "pp", "info": "ao ano"},
            {"id": "cdi", "nome": "CDI", "fonte": "sgs", "codigo": 4389, "n": 400, "formato": "pct", "casas": 2, "variacao": "pp", "info": "ao ano"},
            {"id": "ipca12", "periodo": "mes", "nome": "IPCA 12 meses", "fonte": "sgs", "codigo": 13522, "n": 24, "formato": "pct", "casas": 2, "variacao": "pp", "info": "acumulado"},
            {"id": "ipca", "periodo": "mes", "nome": "IPCA do mês", "fonte": "sgs", "codigo": 433, "n": 24, "formato": "pct", "casas": 2, "variacao": "pp", "info": "variação mensal"},
            {"id": "igpm", "periodo": "mes", "nome": "IGP-M do mês", "fonte": "sgs", "codigo": 189, "n": 24, "formato": "pct", "casas": 2, "variacao": "pp", "info": "variação mensal"},
            {"id": "desemprego", "periodo": "mes", "nome": "Desemprego", "fonte": "sgs", "codigo": 24369, "n": 24, "formato": "pct", "casas": 1, "variacao": "pp", "info": "PNAD Contínua"},
        ]},
        {"nome": "Câmbio e bolsa", "itens": [
            {"id": "dolar", "nome": "Dólar comercial", "fonte": "awesome", "par": "USD-BRL", "formato": "brl", "casas": 4, "variacao": "pct"},
            {"id": "euro", "nome": "Euro comercial", "fonte": "awesome", "par": "EUR-BRL", "formato": "brl", "casas": 4, "variacao": "pct"},
            {"id": "ibov", "nome": "Ibovespa", "fonte": "yahoo", "simbolo": "^BVSP", "formato": "pts", "casas": 0, "variacao": "pct"},
        ]},
    ]},
    {"nome": "Mundo", "grupos": [
        {"nome": "Bolsas", "itens": [
            {"id": "sp500", "nome": "S&P 500", "fonte": "yahoo", "simbolo": "^GSPC", "formato": "pts", "casas": 0, "variacao": "pct", "info": "EUA"},
            {"id": "nasdaq", "nome": "Nasdaq", "fonte": "yahoo", "simbolo": "^IXIC", "formato": "pts", "casas": 0, "variacao": "pct", "info": "EUA"},
            {"id": "dow", "nome": "Dow Jones", "fonte": "yahoo", "simbolo": "^DJI", "formato": "pts", "casas": 0, "variacao": "pct", "info": "EUA"},
        ]},
        {"nome": "Energia e metais", "itens": [
            {"id": "brent", "nome": "Petróleo Brent", "fonte": "yahoo", "simbolo": "BZ=F", "formato": "usd", "casas": 2, "variacao": "pct", "info": "barril"},
            {"id": "wti", "nome": "Petróleo WTI", "fonte": "yahoo", "simbolo": "CL=F", "formato": "usd", "casas": 2, "variacao": "pct", "info": "barril"},
            {"id": "ouro", "nome": "Ouro", "fonte": "yahoo", "simbolo": "GC=F", "formato": "usd", "casas": 2, "variacao": "pct", "info": "onça"},
        ]},
        {"nome": "Alimentos", "itens": [
            {"id": "soja", "nome": "Soja", "fonte": "yahoo", "simbolo": "ZS=F", "formato": "num", "casas": 2, "variacao": "pct", "info": "US¢/bushel · Chicago"},
            {"id": "milho", "nome": "Milho", "fonte": "yahoo", "simbolo": "ZC=F", "formato": "num", "casas": 2, "variacao": "pct", "info": "US¢/bushel · Chicago"},
            {"id": "trigo", "nome": "Trigo", "fonte": "yahoo", "simbolo": "ZW=F", "formato": "num", "casas": 2, "variacao": "pct", "info": "US¢/bushel · Chicago"},
            {"id": "cafe", "nome": "Café arábica", "fonte": "yahoo", "simbolo": "KC=F", "formato": "num", "casas": 2, "variacao": "pct", "info": "US¢/libra · Nova York"},
            {"id": "acucar", "nome": "Açúcar", "fonte": "yahoo", "simbolo": "SB=F", "formato": "num", "casas": 2, "variacao": "pct", "info": "US¢/libra · Nova York"},
        ]},
        {"nome": "Moedas, juros e cripto", "itens": [
            {"id": "eurusd", "nome": "Euro / Dólar", "fonte": "yahoo", "simbolo": "EURUSD=X", "formato": "num", "casas": 4, "variacao": "pct"},
            {"id": "tnx", "nome": "Juros 10 anos EUA", "fonte": "yahoo", "simbolo": "^TNX", "formato": "pct", "casas": 2, "variacao": "pp", "info": "Treasury"},
            {"id": "btc", "nome": "Bitcoin", "fonte": "yahoo", "simbolo": "BTC-USD", "formato": "usd", "casas": 0, "variacao": "pct"},
        ]},
    ]},
]


def _amostrar(valores, n=PONTOS):
    if len(valores) <= n:
        return valores
    passo = (len(valores) - 1) / (n - 1)
    return [valores[round(i * passo)] for i in range(n)]


def _variacao(atual, anterior, tipo):
    if anterior in (None, 0):
        return None
    return round(atual - anterior, 4) if tipo == "pp" else round((atual / anterior - 1) * 100, 4)


def de_sgs(cfg):
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cfg['codigo']}/dados/ultimos/{cfg['n']}?formato=json"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    serie = [(p["data"], float(p["valor"])) for p in r.json() if p.get("valor") not in (None, "")]
    if not serie:
        raise ValueError("série vazia")
    data, atual = serie[-1]
    # compara com o último valor diferente (ex.: Selic só muda nas reuniões do Copom)
    anterior, desde = None, data
    for d, v in reversed(serie[:-1]):
        if v != atual:
            anterior = v
            break
        desde = d  # primeiro dia com o valor atual = data da última mudança
    d, m, a = data.split("/")
    return {"valor": atual, "anterior": anterior, "ref": f"{a}-{m}-{d}",
            "comparado_em": desde if anterior is not None else None, "historico": _amostrar([v for _, v in serie])}


def de_awesome(cfg):
    r = requests.get(f"https://economia.awesomeapi.com.br/json/last/{cfg['par']}", headers=UA, timeout=20)
    r.raise_for_status()
    q = next(iter(r.json().values()))
    atual = float(q["bid"])
    historico = []
    try:
        h = requests.get(f"https://economia.awesomeapi.com.br/json/daily/{cfg['par']}/{PONTOS}", headers=UA, timeout=20)
        h.raise_for_status()
        historico = [float(x["bid"]) for x in reversed(h.json())]
    except Exception:
        pass
    pct = float(q.get("pctChange") or 0)
    anterior = atual / (1 + pct / 100) if pct else None
    return {"valor": atual, "anterior": anterior, "ref": q.get("create_date", "")[:16].replace(" ", "T"),
            "historico": historico or [atual]}


def de_yahoo(cfg):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(cfg['simbolo'])}?range=2mo&interval=1d"
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    meta = res["meta"]
    tempos = res.get("timestamp") or []
    fechamentos = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    pontos = [(t, c) for t, c in zip(tempos, fechamentos) if c is not None]
    atual = meta.get("regularMarketPrice") or (pontos[-1][1] if pontos else None)
    if atual is None:
        raise ValueError("sem cotação")
    # fechamento do pregão anterior ao último ponto
    anterior = pontos[-2][1] if len(pontos) >= 2 else meta.get("chartPreviousClose")
    quando = meta.get("regularMarketTime") or (pontos[-1][0] if pontos else None)
    ref = datetime.fromtimestamp(quando, tz=timezone.utc).astimezone(TZ).strftime("%Y-%m-%dT%H:%M") if quando else ""
    return {"valor": atual, "anterior": anterior, "ref": ref,
            "historico": [c for _, c in pontos][-PONTOS:]}


FONTES = {"sgs": de_sgs, "awesome": de_awesome, "yahoo": de_yahoo}


def main():
    try:
        antigo = json.load(open(SAIDA, encoding="utf-8"))
        anteriores = {i["id"]: i for s in antigo.get("secoes", []) for g in s["grupos"] for i in g["itens"]}
    except Exception:
        anteriores = {}

    ok = falhas = 0
    secoes = []
    for s in SECOES:
        grupos = []
        for g in s["grupos"]:
            itens = []
            for cfg in g["itens"]:
                base = {k: cfg[k] for k in ("id", "nome", "formato", "casas", "variacao", "periodo") if k in cfg}
                if cfg.get("info"):
                    base["info"] = cfg["info"]
                try:
                    dado = FONTES[cfg["fonte"]](cfg)
                    item = {**base,
                            "valor": round(dado["valor"], 6),
                            "var": _variacao(dado["valor"], dado.get("anterior"), cfg["variacao"]),
                            "ref": dado["ref"],
                            "hist": [round(v, 6) for v in dado["historico"]]}
                    if dado.get("comparado_em"):
                        item["desde"] = dado["comparado_em"]
                    ok += 1
                    print(f"  ✓ {cfg['nome']}: {item['valor']}")
                except Exception as e:
                    falhas += 1
                    print(f"  ✗ {cfg['nome']}: {e.__class__.__name__} {str(e)[:80]}")
                    if cfg["id"] not in anteriores:
                        continue
                    item = {**anteriores[cfg["id"]], **base, "desatualizado": True}
                itens.append(item)
            if itens:
                grupos.append({"nome": g["nome"], "itens": itens})
        secoes.append({"nome": s["nome"], "grupos": grupos})

    if ok == 0 and anteriores:
        print("Nenhuma fonte respondeu; arquivo mantido como estava.")
        return
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    json.dump({"atualizado": datetime.now(TZ).isoformat(timespec="seconds"), "secoes": secoes},
              open(SAIDA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{ok} indicadores atualizados, {falhas} com falha")


if __name__ == "__main__":
    main()
