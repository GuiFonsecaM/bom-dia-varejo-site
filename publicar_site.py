"""
Envia as notícias do boletim do WhatsApp para o site (GitHub Pages), sem limite de dias.

Estrutura gravada no repositório do site:
    data/anos.json              -> lista de anos com notícias
    data/indice/AAAA.json       -> índice leve do ano (título, categoria, fonte, resumo) para listar dias e buscar
    data/dias/AAAA-MM-DD.json   -> as notícias completas de cada dia

Nada é apagado: cada dia vira um arquivo novo, e o site só baixa o que precisa.
Os três arquivos são gravados num único commit.

Uso no gerador do boletim, logo depois do envio pelo Green-API:

    from publicar_site import publicar_no_site
    publicar_no_site(noticias)              # usa a data de hoje (Brasília)
    publicar_no_site(noticias, "2026-11-08") # ou uma data específica

Cada notícia é um dict:
    {
      "titulo": "...",
      "topicos": ["...", "..."],   # os mesmos tópicos do WhatsApp
      "fonte": "Valor Econômico",   # opcional
      "link": "https://...",        # link original
      "categoria": "Varejo",        # opcional
      "imagem": "https://..."       # opcional
    }

Variáveis de ambiente (secrets do GitHub Actions):
    SITE_REPO    ex.: GuiFonsecaM/bom-dia-varejo-site
    SITE_TOKEN   token do GitHub com permissão "Contents: Read and write" nesse repositório
    SITE_BRANCH  opcional, padrão "main"
"""
import base64
import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("America/Sao_Paulo")
RESUMO_MAX = 160


class _GitHub:
    def __init__(self):
        self.repo = os.environ["SITE_REPO"]
        self.branch = os.environ.get("SITE_BRANCH", "main")
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {os.environ['SITE_TOKEN']}",
            "Accept": "application/vnd.github+json",
        })
        self.api = f"https://api.github.com/repos/{self.repo}"

    def _req(self, metodo, caminho, **kw):
        r = self.s.request(metodo, self.api + caminho, timeout=30, **kw)
        if r.status_code >= 400 and r.status_code != 404:
            raise RuntimeError(f"GitHub {metodo} {caminho}: {r.status_code} {r.text[:300]}")
        return r

    def ler_json(self, caminho, padrao):
        r = self._req("GET", f"/contents/{caminho}", params={"ref": self.branch})
        if r.status_code == 404:
            return padrao
        return json.loads(base64.b64decode(r.json()["content"]).decode("utf-8"))

    def commit(self, arquivos, mensagem):
        """Grava vários arquivos num único commit. arquivos = {caminho: objeto_json}."""
        ref = self._req("GET", f"/git/ref/heads/{self.branch}").json()
        pai = ref["object"]["sha"]
        base_tree = self._req("GET", f"/git/commits/{pai}").json()["tree"]["sha"]
        tree = [{
            "path": caminho,
            "mode": "100644",
            "type": "blob",
            "content": json.dumps(obj, ensure_ascii=False, indent=1) + "\n",
        } for caminho, obj in arquivos.items()]
        nova_tree = self._req("POST", "/git/trees", json={"base_tree": base_tree, "tree": tree}).json()["sha"]
        novo = self._req("POST", "/git/commits", json={
            "message": mensagem, "tree": nova_tree, "parents": [pai],
        }).json()["sha"]
        r = self.s.patch(f"{self.api}/git/refs/heads/{self.branch}", json={"sha": novo}, timeout=30)
        if r.status_code == 422:      # a branch andou enquanto montávamos o commit
            return False
        r.raise_for_status()
        return True


def _limpar(n):
    item = {
        "titulo": str(n.get("titulo", "")).strip(),
        "topicos": [str(t).strip() for t in n.get("topicos", []) if str(t).strip()],
        "fonte": str(n.get("fonte", "")).strip(),
        "link": str(n.get("link", "")).strip(),
        "categoria": str(n.get("categoria", "")).strip(),
        "imagem": str(n.get("imagem", "")).strip(),
    }
    return {k: v for k, v in item.items() if v}


def _resumo(n):
    t = (n.get("topicos") or [""])[0]
    return t if len(t) <= RESUMO_MAX else t[:RESUMO_MAX - 1].rsplit(" ", 1)[0] + "…"


def publicar_no_site(noticias, data=None, tentativas=3):
    agora = datetime.now(TZ)
    data = data or agora.strftime("%Y-%m-%d")
    ano = int(data[:4])
    gh = _GitHub()

    for tentativa in range(1, tentativas + 1):
        # 1) Arquivo do dia: junta com o que já existe, sem duplicar
        dia = gh.ler_json(f"data/dias/{data}.json", {"data": data, "noticias": []})
        vistos = {(x.get("link") or x["titulo"]) for x in dia["noticias"]}
        for n in map(_limpar, noticias):
            if not n.get("titulo"):
                continue
            chave = n.get("link") or n["titulo"]
            if chave not in vistos:
                dia["noticias"].append(n)
                vistos.add(chave)

        # 2) Índice do ano: só o essencial para listar dias e buscar
        indice = gh.ler_json(f"data/indice/{ano}.json", {"ano": ano, "dias": []})
        dias = {d["data"]: d for d in indice["dias"]}
        dias[data] = {"data": data, "n": [
            {k: v for k, v in {"t": n["titulo"], "c": n.get("categoria", ""),
                               "f": n.get("fonte", ""), "r": _resumo(n)}.items() if v}
            for n in dia["noticias"]
        ]}
        indice["dias"] = sorted(dias.values(), key=lambda d: d["data"], reverse=True)

        # 3) Lista de anos
        anos = gh.ler_json("data/anos.json", {"anos": []})
        anos["anos"] = sorted(set(map(int, anos.get("anos", []))) | {ano}, reverse=True)
        anos["atualizado"] = agora.isoformat(timespec="seconds")

        ok = gh.commit({
            f"data/dias/{data}.json": dia,
            f"data/indice/{ano}.json": indice,
            "data/anos.json": anos,
        }, f"Notícias de {data}")
        if ok:
            print(f"Site atualizado: {len(dia['noticias'])} notícias em {data}")
            return
        time.sleep(2 * tentativa)  # outro commit entrou no meio; lê de novo e tenta outra vez

    raise RuntimeError("Não foi possível atualizar o site depois de várias tentativas")


if __name__ == "__main__":
    # Teste rápido: python publicar_site.py noticias.json [AAAA-MM-DD]
    import sys
    lista = json.load(open(sys.argv[1], encoding="utf-8"))
    publicar_no_site(lista, sys.argv[2] if len(sys.argv) > 2 else None)
