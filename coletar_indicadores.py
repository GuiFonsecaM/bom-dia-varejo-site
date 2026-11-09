"""
Atualiza os indicadores do site (aba "Indicadores") a cada rodada do workflow, com histórico.

Para cada indicador calcula:
- a variação mais recente e DESDE QUANDO ela vale (vs. fechamento anterior, vs. mês anterior
  ou desde a última decisão do Copom);
- a sequência atual de altas ou quedas e quando ela começou (ex.: "3º pregão em alta, desde 04/11");
- a variação em 12 meses;
- um histórico de 12 meses para o minigráfico.

Fontes gratuitas, sem chave (cada indicador tenta, na ordem, até uma responder):
- Yahoo Finance: dólar, euro, bolsas, petróleo, ouro, commodities, juros dos EUA, bitcoin (1 ano diário)
- IBGE (SIDRA), Banco Central (SGS) e Ipeadata: IPCA, IGP-M, desemprego, Selic, CDI
  (o Banco Central costuma não responder a servidores fora do Brasil, como os do GitHub)
- BrasilAPI: Selic, CDI e IPCA atuais; o histórico é guardado rodada a rodada em data/historico/
- AwesomeAPI: reserva para dólar e euro

Grava data/indicadores.json. Se uma fonte falhar, mantém o último valor e marca como desatualizado.
Rodar à mão:  python coletar_indicadores.py
"""
import json
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("America/Sao_Paulo")
AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(AQUI, "data", "indicadores.json")
PASTA_HIST = os.path.join(AQUI, "data", "historico")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
PONTOS = 60  # pontos do minigráfico (12 meses)

# Decisões do Copom (data da reunião → Selic meta). Base para o histórico quando o Banco Central não responde;
# mudanças novas entram sozinhas, rodada a rodada. Fonte: calendário/decisões do Copom 2025–2026.
SEMENTES = {
    "selic": [("2025-06-18", 15.00), ("2026-03-18", 14.75), ("2026-04-29", 14.50),
              ("2026-06-17", 14.25), ("2026-08-05", 14.00), ("2026-09-16", 13.75)],
}
SEMENTES["cdi"] = [(d, round(v - 0.10, 2)) for d, v in SEMENTES["selic"]]  # CDI acompanha a Selic − 0,10 p.p.

# tipo: diario (cotação), degrau (taxa que só muda em decisões), mensal (dado mensal)
# formato: pct | brl | usd | pts | num     variacao: pct (variação %) | pp (pontos percentuais)
SECOES = [
    {"nome": "Brasil", "grupos": [
        {"nome": "Juros e inflação", "itens": [
            {"id": "selic", "nome": "Selic (meta)", "tipo": "degrau", "formato": "pct", "casas": 2, "variacao": "pp", "info": "ao ano",
             "fontes": [("sgs", {"codigo": 432, "n": 800}), ("brasilapi", {"sigla": "selic"})]},
            {"id": "cdi", "nome": "CDI", "tipo": "degrau", "formato": "pct", "casas": 2, "variacao": "pp", "info": "ao ano",
             "fontes": [("sgs", {"codigo": 4389, "n": 800}), ("brasilapi", {"sigla": "cdi"})]},
            {"id": "ipca12", "nome": "IPCA 12 meses", "tipo": "mensal", "formato": "pct", "casas": 2, "variacao": "pp", "info": "acumulado",
             "fontes": [("ibge", {"tabela": 1737, "variavel": 2265}), ("ibge", {"tabela": 7060, "variavel": 2265, "classe": "315[7169]"}),
                        ("sgs", {"codigo": 13522, "n": 30}), ("ipea_indice", {"codigo": "PRECOS12_IPCA12", "modo": "12m"}),
                        ("brasilapi", {"sigla": "ipca"})]},
            {"id": "ipca", "nome": "IPCA do mês", "tipo": "mensal", "formato": "pct", "casas": 2, "variacao": "pp", "info": "variação mensal",
             "fontes": [("ibge", {"tabela": 1737, "variavel": 63}), ("ibge", {"tabela": 7060, "variavel": 63, "classe": "315[7169]"}),
                        ("sgs", {"codigo": 433, "n": 30}), ("ipea_indice", {"codigo": "PRECOS12_IPCA12", "modo": "mes"})]},
            {"id": "igpm", "nome": "IGP-M do mês", "tipo": "mensal", "formato": "pct", "casas": 2, "variacao": "pp", "info": "variação mensal",
             "fontes": [("sgs", {"codigo": 189, "n": 30}), ("ipea", {"codigo": "IGP12_IGPMG12"})]},
            {"id": "desemprego", "nome": "Desemprego", "tipo": "mensal", "formato": "pct", "casas": 1, "variacao": "pp", "info": "PNAD Contínua · trimestre móvel",
             "fontes": [("ibge", {"tabela": 6381, "variavel": 4099}), ("sgs", {"codigo": 24369, "n": 30}), ("ipea", {"codigo": "PNADC12_TDESOC12"})]},
        ]},
        {"nome": "Câmbio e bolsa", "itens": [
            {"id": "dolar", "nome": "Dólar comercial", "tipo": "diario", "formato": "brl", "casas": 4, "variacao": "pct", "unidade": "dia",
             "fontes": [("yahoo", {"simbolo": "BRL=X"}), ("awesome", {"par": "USD-BRL"})]},
            {"id": "euro", "nome": "Euro comercial", "tipo": "diario", "formato": "brl", "casas": 4, "variacao": "pct", "unidade": "dia",
             "fontes": [("yahoo", {"simbolo": "EURBRL=X"}), ("awesome", {"par": "EUR-BRL"})]},
            {"id": "ibov", "nome": "Ibovespa", "tipo": "diario", "formato": "pts", "casas": 0, "variacao": "pct",
             "fontes": [("yahoo", {"simbolo": "^BVSP"})]},
        ]},
    ]},
    {"nome": "Mundo", "grupos": [
        {"nome": "Bolsas", "itens": [
            {"id": "sp500", "nome": "S&P 500", "tipo": "diario", "formato": "pts", "casas": 0, "variacao": "pct", "info": "EUA", "fontes": [("yahoo", {"simbolo": "^GSPC"})]},
            {"id": "nasdaq", "nome": "Nasdaq", "tipo": "diario", "formato": "pts", "casas": 0, "variacao": "pct", "info": "EUA", "fontes": [("yahoo", {"simbolo": "^IXIC"})]},
            {"id": "dow", "nome": "Dow Jones", "tipo": "diario", "formato": "pts", "casas": 0, "variacao": "pct", "info": "EUA", "fontes": [("yahoo", {"simbolo": "^DJI"})]},
        ]},
        {"nome": "Energia e metais", "itens": [
            {"id": "brent", "nome": "Petróleo Brent", "tipo": "diario", "formato": "usd", "casas": 2, "variacao": "pct", "info": "barril", "fontes": [("yahoo", {"simbolo": "BZ=F"})]},
            {"id": "wti", "nome": "Petróleo WTI", "tipo": "diario", "formato": "usd", "casas": 2, "variacao": "pct", "info": "barril", "fontes": [("yahoo", {"simbolo": "CL=F"})]},
            {"id": "ouro", "nome": "Ouro", "tipo": "diario", "formato": "usd", "casas": 2, "variacao": "pct", "info": "onça", "fontes": [("yahoo", {"simbolo": "GC=F"})]},
        ]},
        {"nome": "Alimentos", "itens": [
            {"id": "soja", "nome": "Soja", "tipo": "diario", "formato": "num", "casas": 2, "variacao": "pct", "info": "US¢/bushel · Chicago", "fontes": [("yahoo", {"simbolo": "ZS=F"})]},
            {"id": "milho", "nome": "Milho", "tipo": "diario", "formato": "num", "casas": 2, "variacao": "pct", "info": "US¢/bushel · Chicago", "fontes": [("yahoo", {"simbolo": "ZC=F"})]},
            {"id": "trigo", "nome": "Trigo", "tipo": "diario", "formato": "num", "casas": 2, "variacao": "pct", "info": "US¢/bushel · Chicago", "fontes": [("yahoo", {"simbolo": "ZW=F"})]},
            {"id": "cafe", "nome": "Café arábica", "tipo": "diario", "formato": "num", "casas": 2, "variacao": "pct", "info": "US¢/libra · Nova York", "fontes": [("yahoo", {"simbolo": "KC=F"})]},
            {"id": "acucar", "nome": "Açúcar", "tipo": "diario", "formato": "num", "casas": 2, "variacao": "pct", "info": "US¢/libra · Nova York", "fontes": [("yahoo", {"simbolo": "SB=F"})]},
        ]},
        {"nome": "Moedas, juros e cripto", "itens": [
            {"id": "eurusd", "nome": "Euro / Dólar", "tipo": "diario", "formato": "num", "casas": 4, "variacao": "pct", "unidade": "dia", "fontes": [("yahoo", {"simbolo": "EURUSD=X"})]},
            {"id": "tnx", "nome": "Juros 10 anos EUA", "tipo": "diario", "formato": "pct", "casas": 2, "variacao": "pp", "info": "Treasury", "fontes": [("yahoo", {"simbolo": "^TNX"})]},
            {"id": "btc", "nome": "Bitcoin", "tipo": "diario", "formato": "usd", "casas": 0, "variacao": "pct", "unidade": "dia", "fontes": [("yahoo", {"simbolo": "BTC-USD"})]},
        ]},
    ]},
]


# ---------------------------------------------------------------- fontes (todas devolvem uma série [(AAAA-MM-DD, valor)])

def de_sgs(cfg, _id):
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cfg['codigo']}/dados/ultimos/{cfg['n']}?formato=json"
    r = requests.get(url, headers=UA, timeout=12)
    r.raise_for_status()
    serie = []
    for p in r.json():
        if p.get("valor") in (None, ""):
            continue
        d, m, a = p["data"].split("/")
        serie.append((f"{a}-{m}-{d}", float(p["valor"])))
    return {"serie": serie}


def de_ibge(cfg, _id):
    url = (f"https://servicodados.ibge.gov.br/api/v3/agregados/{cfg['tabela']}/periodos/-30/variaveis/{cfg['variavel']}"
           f"?localidades=N1[all]" + (f"&classificacao={cfg['classe']}" if cfg.get("classe") else ""))
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    bruto = r.json()[0]["resultados"][0]["series"][0]["serie"]
    return {"serie": [(f"{p[:4]}-{p[4:6]}-01", float(v)) for p, v in sorted(bruto.items()) if v not in (None, "", "-", "...", "X")]}


def _ipea(codigo):
    ultimo = None
    for base in ("https://www.ipeadata.gov.br", "http://www.ipeadata.gov.br"):
        try:
            r = requests.get(f"{base}/api/odata4/ValoresSerie(SERCODIGO='{codigo}')", headers=UA, timeout=25)
            r.raise_for_status()
            return [(v["VALDATA"][:10], float(v["VALVALOR"])) for v in r.json()["value"] if v.get("VALVALOR") is not None]
        except Exception as e:
            ultimo = e
    raise ultimo


def de_ipea(cfg, _id):
    return {"serie": _ipea(cfg["codigo"])[-30:]}


def de_ipea_indice(cfg, _id):
    """Série de número-índice (ex.: IPCA) → variação do mês ou acumulada em 12 meses, em %."""
    idx = _ipea(cfg["codigo"])
    passo = 12 if cfg["modo"] == "12m" else 1
    serie = [(idx[i][0][:7] + "-01", round((idx[i][1] / idx[i - passo][1] - 1) * 100, 2)) for i in range(passo, len(idx))]
    return {"serie": serie[-30:]}


_cache_brasilapi = None


def de_brasilapi(cfg, id_):
    """Valor atual (sem histórico). O histórico é guardado em data/historico/<id>.json rodada a rodada."""
    global _cache_brasilapi
    if _cache_brasilapi is None:
        r = requests.get("https://brasilapi.com.br/api/taxas/v1", headers=UA, timeout=20)
        r.raise_for_status()
        _cache_brasilapi = {t["nome"].lower(): float(t["valor"]) for t in r.json()}
    if cfg["sigla"] not in _cache_brasilapi:
        raise ValueError("taxa não encontrada")
    atual = _cache_brasilapi[cfg["sigla"]]
    hoje = datetime.now(TZ).date().isoformat()
    caminho = os.path.join(PASTA_HIST, f"{id_}.json")
    try:
        serie = [tuple(p) for p in json.load(open(caminho, encoding="utf-8"))["serie"]]
    except Exception:
        serie = list(SEMENTES.get(id_, []))
    if not serie or serie[-1][1] != atual:
        serie.append((hoje, atual))
    os.makedirs(PASTA_HIST, exist_ok=True)
    json.dump({"serie": serie[-500:]}, open(caminho, "w", encoding="utf-8"), ensure_ascii=False)
    return {"serie": serie, "consulta": hoje}


def de_awesome(cfg, _id):
    r = requests.get(f"https://economia.awesomeapi.com.br/json/daily/{cfg['par']}/365", headers=UA, timeout=25)
    r.raise_for_status()
    serie = {}
    for x in r.json():
        d = datetime.fromtimestamp(int(x["timestamp"]), tz=timezone.utc).astimezone(TZ)
        serie.setdefault(d.date().isoformat(), float(x["bid"]))   # o mais recente de cada dia
    return {"serie": sorted(serie.items()), "ref": max(serie)}


def de_yahoo(cfg, _id):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(cfg['simbolo'])}?range=1y&interval=1d"
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    meta = res["meta"]
    tempos = res.get("timestamp") or []
    fech = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    serie = {}
    for t, c in zip(tempos, fech):
        if c is not None:
            serie[datetime.fromtimestamp(t, tz=timezone.utc).astimezone(TZ).date().isoformat()] = c
    preco, quando = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
    ref = None
    if preco is not None and quando:
        momento = datetime.fromtimestamp(quando, tz=timezone.utc).astimezone(TZ)
        serie[momento.date().isoformat()] = preco          # cotação mais recente no dia do último negócio
        ref = momento.strftime("%Y-%m-%dT%H:%M")
    if not serie:
        raise ValueError("sem cotação")
    return {"serie": sorted(serie.items()), "ref": ref}


FONTES = {"sgs": de_sgs, "ibge": de_ibge, "ipea": de_ipea, "ipea_indice": de_ipea_indice,
          "brasilapi": de_brasilapi, "awesome": de_awesome, "yahoo": de_yahoo}


# ---------------------------------------------------------------- análise da série

def _d(iso):
    return date.fromisoformat(iso[:10])


def _var(atual, base, tipo):
    if base in (None, 0):
        return None
    return round(atual - base, 4) if tipo == "pp" else round((atual / base - 1) * 100, 4)


def _sinal(x, eps):
    return 0 if abs(x) <= eps else (1 if x > 0 else -1)


def _amostrar(pontos, n=PONTOS):
    if len(pontos) <= n:
        return pontos
    passo = (len(pontos) - 1) / (n - 1)
    return [pontos[round(i * passo)] for i in range(n)]


def _degraus(serie):
    """Só os pontos em que o valor mudou: [(data em que passou a valer, valor)]."""
    out = []
    for d, v in serie:
        if not out or v != out[-1][1]:
            out.append((d, v))
    return out


def _valor_em(degraus, dia):
    v = None
    for d, x in degraus:
        if _d(d) <= dia:
            v = x
        else:
            break
    return v


def analisar(serie, cfg):
    serie = sorted((d[:10], v) for d, v in serie)
    tipo, tv = cfg["tipo"], cfg["variacao"]
    eps = 1e-9 if tv == "pp" and tipo != "diario" else 1e-6
    ult_data, atual = serie[-1]
    # taxas em degrau só registram as mudanças: a referência é hoje, não a data da última mudança
    hoje = datetime.now(TZ).date() if tipo == "degrau" else _d(ult_data)
    out = {"valor": round(atual, 6)}

    if tipo == "degrau":
        deg = _degraus(serie)
        out["vigente_desde"] = deg[-1][0]                       # desde quando vale o nível atual
        if len(deg) >= 2:
            out["var"] = _var(atual, deg[-2][1], tv)
            out["var_base"] = deg[-1][0]                        # a mudança aconteceu nesta data
        sinais = [_sinal(deg[i][1] - deg[i - 1][1], eps) for i in range(1, len(deg))]
        pontos = [deg[i][0] for i in range(1, len(deg))]
        um_ano = hoje.replace(year=hoje.year - 1)
        base12 = _valor_em(deg, um_ano)
        if base12 is not None:
            out["var12"], out["base12"] = _var(atual, base12, tv), um_ano.isoformat()
        # minigráfico: valor mês a mês nos últimos 12 meses
        hist = []
        for k in range(12, -1, -1):
            dia = hoje - timedelta(days=30 * k)
            v = _valor_em(deg, dia)
            if v is not None:
                hist.append((dia.isoformat(), v))
    else:
        if len(serie) >= 2:
            out["var"] = _var(atual, serie[-2][1], tv)
            out["var_base"] = serie[-2][0]                      # comparação com este dia/mês
        sinais = [_sinal(serie[i][1] - serie[i - 1][1], eps) for i in range(1, len(serie))]
        pontos = [serie[i - 1][0] for i in range(1, len(serie))]  # a sequência começa no ponto anterior à 1ª alta/queda
        um_ano = hoje - timedelta(days=365)
        anteriores = [p for p in serie if _d(p[0]) <= um_ano + (timedelta(days=0) if tipo == "diario" else timedelta(days=5))]
        if anteriores:
            base_d, base_v = anteriores[-1]
            if (um_ano - _d(base_d)).days <= 40:
                out["var12"], out["base12"] = _var(atual, base_v, tv), base_d
        hist = [p for p in serie if _d(p[0]) >= um_ano]

    # sequência atual de altas ou quedas
    if sinais and sinais[-1] != 0:
        direcao, n = sinais[-1], 0
        for s in reversed(sinais):
            if s != direcao:
                break
            n += 1
        out["seq"] = {"dir": "alta" if direcao > 0 else "queda", "n": n, "desde": pontos[len(sinais) - n]}
    hist = _amostrar(hist)
    if hist:
        out["hist"] = [round(v, 6) for _, v in hist]
        out["hist_ini"], out["hist_fim"] = hist[0][0], hist[-1][0]
    return out


def buscar(cfg):
    erros = []
    for nome, params in cfg["fontes"]:
        try:
            dado = FONTES[nome]({**params}, cfg["id"])
            if not dado.get("serie"):
                raise ValueError("série vazia")
            return nome, dado, erros
        except Exception as e:
            erros.append(f"{nome}: {e.__class__.__name__} {str(e)[:60]}")
    raise RuntimeError(" | ".join(erros))


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
                base = {k: cfg[k] for k in ("id", "nome", "tipo", "formato", "casas", "variacao", "unidade", "info") if k in cfg}
                try:
                    fonte, dado, erros = buscar(cfg)
                    item = {**base, **analisar(dado["serie"], cfg), "fonte": fonte}
                    if cfg["tipo"] == "mensal" and fonte != "brasilapi":
                        item["ref"] = dado["serie"][-1][0][:7]             # mês de referência
                    elif dado.get("consulta"):
                        item["ref"] = dado["consulta"]
                        item["ref_tipo"] = "consulta"
                    else:
                        item["ref"] = dado.get("ref") or dado["serie"][-1][0]
                    if fonte == "brasilapi" and cfg["tipo"] == "mensal":
                        item["tipo"] = "consulta"                           # sem mês de referência confiável
                    if erros:
                        item["fontes_falharam"] = erros
                    ok += 1
                    seq = item.get("seq")
                    print(f"  ✓ {cfg['nome']}: {item['valor']} ({fonte})"
                          + (f" · {seq['n']}x {seq['dir']} desde {seq['desde']}" if seq else ""))
                except Exception as e:
                    falhas += 1
                    print(f"  ✗ {cfg['nome']}: {str(e)[:200]}")
                    if cfg["id"] not in anteriores:
                        continue
                    item = {**anteriores[cfg["id"]], **base, "desatualizado": True, "erro": str(e)[:300]}
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
