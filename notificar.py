"""
Envia uma notificação para quem ativou o sino do site sempre que entram notícias novas.

Compara as notícias de hoje e de ontem entre o commit de antes da rodada (base) e o atual.
- 1 notícia nova  → título da notícia
- várias          → "N novas notícias" + a primeira manchete
Se não houver notícia nova (ex.: só indicadores ou imagens mudaram), não envia nada.

Uso (no workflow, depois de publicar o site):  python3 notificar.py <sha_base>
Variáveis: ONESIGNAL_APP_ID, ONESIGNAL_API_KEY, ONESIGNAL_SEGMENTO (opcional), SITE_URL (opcional)
Teste sem enviar: python3 notificar.py <sha_base> --teste
"""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

AQUI = os.path.dirname(os.path.abspath(__file__))
TZ = ZoneInfo("America/Sao_Paulo")


def site_url():
    if os.environ.get("SITE_URL"):
        return os.environ["SITE_URL"].rstrip("/") + "/"
    try:
        dominio = open(os.path.join(AQUI, "CNAME")).read().strip()
        if dominio:
            return f"https://{dominio}/"
    except OSError:
        pass
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    dono, _, nome = repo.partition("/")
    return f"https://{dono.lower()}.github.io/{nome}/" if repo else ""


def noticias_no_commit(sha, caminho):
    if not sha or set(sha) == {"0"}:
        return []
    subprocess.run(["git", "fetch", "-q", "--depth=1", "origin", sha], cwd=AQUI, capture_output=True)
    r = subprocess.run(["git", "show", f"{sha}:{caminho}"], cwd=AQUI, capture_output=True, text=True)
    if r.returncode != 0:
        return []
    try:
        return json.loads(r.stdout).get("noticias", [])
    except json.JSONDecodeError:
        return []


def novas_desde(sha):
    hoje = datetime.now(TZ).date()
    novas = []
    for i in range(2):
        data = (hoje - timedelta(days=i)).isoformat()
        caminho = f"data/dias/{data}.json"
        local = os.path.join(AQUI, caminho)
        if not os.path.exists(local):
            continue
        atuais = json.load(open(local, encoding="utf-8")).get("noticias", [])
        antes = {(n.get("link") or n.get("titulo")) for n in noticias_no_commit(sha, caminho)}
        novas += [(data, n) for n in atuais if (n.get("link") or n.get("titulo")) not in antes]
    return novas


def main():
    if len(sys.argv) < 2:
        sys.exit("uso: python3 notificar.py <sha_base> [--teste]")
    novas = novas_desde(sys.argv[1])
    if not novas:
        print("Nenhuma notícia nova — sem notificação.")
        return

    data, primeira = novas[0]
    url = site_url()
    if len(novas) == 1:
        titulo = f"Bom dia varejo · {primeira.get('categoria') or 'Notícia'}"
        texto = primeira["titulo"]
    else:
        titulo = f"Bom dia varejo · {len(novas)} novas notícias"
        texto = f"{primeira['titulo']} e mais {len(novas) - 1}"
    corpo = {
        "app_id": os.environ.get("ONESIGNAL_APP_ID", ""),
        "target_channel": "push",
        "isAnyWeb": True,
        "included_segments": [os.environ.get("ONESIGNAL_SEGMENTO") or "Total Subscriptions"],
        "headings": {"en": titulo, "pt": titulo},
        "contents": {"en": texto, "pt": texto},
        "url": f"{url}?dia={data}" if url else None,
        "chrome_web_icon": f"{url}icons/icon-192.png" if url else None,
        "chrome_web_image": f"{url}{primeira['imagem']}" if url and primeira.get("imagem", "").startswith("img/") else None,
    }
    corpo = {k: v for k, v in corpo.items() if v is not None}
    print(f"{len(novas)} nova(s): {titulo} — {texto}")

    if "--teste" in sys.argv:
        print(json.dumps(corpo, ensure_ascii=False, indent=1))
        return
    chave = os.environ.get("ONESIGNAL_API_KEY")
    if not corpo["app_id"] or not chave:
        print("OneSignal não configurado (ONESIGNAL_APP_ID / ONESIGNAL_API_KEY) — sem notificação.")
        return
    req = urllib.request.Request(
        "https://api.onesignal.com/notifications?c=push",
        data=json.dumps(corpo).encode(), method="POST",
        headers={"Authorization": f"Key {chave}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print("Notificação enviada:", r.status, r.read().decode()[:200])


if __name__ == "__main__":
    main()
