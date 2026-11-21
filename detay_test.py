#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tek seferlik maç detay / istatistik uç nokta keşif betiği.
Kullanım:
  python detay_test.py            # Canlı futbol listesinden ilk maçın Eid'sini alır
  python detay_test.py 12345678   # Belirli bir Eid'yi test eder
"""
import json
import random
import sys
import requests

LIVE_FB_URL = "https://prod-public-api.livescore.com/v1/api/app/live/soccer/1?MD=1"
CANDIDATE_TEMPLATES = [
    "https://prod-public-api.livescore.com/v1/api/app/match/soccer/{eid}",
    "https://prod-public-api.livescore.com/v1/api/app/event/soccer/{eid}",
    "https://prod-public-api.livescore.com/v1/api/app/statistics/soccer/{eid}",
    "https://prod-public-api.livescore.com/v1/api/app/incidents/soccer/{eid}",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.livescore.com/",
}
HINTS = ("stat", "shot", "att", "cor", "poss", "inc", "card", "red", "yel", "foul", "xg", "goal", "ev")


def find_hints(obj, prefix="", out=None):
    if out is None:
        out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            path = f"{prefix}.{k}" if prefix else str(k)
            if any(h in kl for h in HINTS):
                out.add(path)
            find_hints(v, path, out)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj[:5]):
            find_hints(item, f"{prefix}[{idx}]", out)
    return sorted(out)


def pick_first_eid():
    r = requests.get(LIVE_FB_URL, headers=HEADERS, timeout=12)
    r.raise_for_status()
    data = r.json()
    for st in data.get("Stages") or []:
        for ev in st.get("Events") or []:
            if ev.get("Eid"):
                t1 = ev.get("T1", [{}])[0].get("Nm", "?") if isinstance(ev.get("T1"), list) else "?"
                t2 = ev.get("T2", [{}])[0].get("Nm", "?") if isinstance(ev.get("T2"), list) else "?"
                print(f"Canlı örnek maç: {t1} - {t2} | Eid={ev.get('Eid')} | Eps={ev.get('Eps')}")
                return str(ev.get("Eid"))
    return None


def main():
    eid = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else pick_first_eid()
    if not eid:
        print("Test edilecek Eid bulunamadı.")
        return

    print(f"\n--- Eid={eid} için uç nokta kontrolü ---")
    for tmpl in CANDIDATE_TEMPLATES:
        url = tmpl.format(eid=eid)
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            print(f"\nURL: {url}\nDurum: HTTP {r.status_code}")
            if r.status_code == 200:
                try:
                    payload = r.json()
                except Exception:
                    print("JSON değil, ilk 300 karakter:", r.text[:300])
                    continue
                if isinstance(payload, dict):
                    print("Üst düzey anahtarlar:", list(payload.keys()))
                hints = find_hints(payload)
                print("İstatistik/olay ipucu yolları:", hints[:30] if hints else "yok")
                preview = json.dumps(payload, ensure_ascii=False)[:700]
                print("Önizleme:", preview)
        except Exception as exc:
            print(f"\nURL: {url}\nHata: {exc}")


if __name__ == "__main__":
    main()
