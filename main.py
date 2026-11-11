import os
import requests
import time

API_KEY = "3046beec0ef4a4346c9dcaa602e87315"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SKIP_FOOTBALL_LEAGUES = ["women", "u19", "u21", "u20", "friendly", "hazırlık", "reserve", "non league", "regional"]
SKIP_BASKETBALL_LEAGUES = ["women", "u18", "u19", "u20", "u21", "3x3", "youth"]

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram hatasi: {e}")

def check_live_basketball():
    if not API_KEY: return
    url = "https://v1.basketball.api-sports.io/games?live=all"
    headers = {"x-apisports-key": API_KEY, "x-rapidapi-host": "v1.basketball.api-sports.io"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200: return
        data = res.json()
    except Exception: return

    if "response" not in data or not data["response"]: return

    for item in data["response"]:
        league_name = item.get("league", {}).get("name", "").lower()
        if any(kw in league_name for kw in SKIP_BASKETBALL_LEAGUES): continue

        status = item.get("status", {}).get("short", "")
        teams = item.get("teams", {})
        home_name = teams.get("home", {}).get("name", "Ev")
        away_name = teams.get("away", {}).get("name", "Deplasman")

        scores = item.get("scores", {})
        h_q1 = scores.get("home", {}).get("quarter_1", 0) or 0
        a_q1 = scores.get("away", {}).get("quarter_1", 0) or 0
        total_score = (scores.get("home", {}).get("total", 0) or 0) + (scores.get("away", {}).get("total", 0) or 0)
        q1_total = h_q1 + a_q1

        if status in ["Q2", "Q3"] and q1_total >= 54:
            msg = (f"🏀 **BASKETBOL ALARMI (ALT SİNYALİ)** 🏀\n\n"
                   f"⚔️ **Maç:** {home_name} - {away_name}\n"
                   f"🏆 **Lig:** {item.get('league', {}).get('name')}\n"
                   f"⏱️ **Periyot:** {status} | Toplam Skor: {total_score}\n"
                   f"📊 **1. Çeyrek Skoru:** {h_q1} - {a_q1} ({q1_total} Sayı)\n\n"
                   f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ALT**\n"
                   f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55 Bandı\n"
                   f"📌 **Sebep:** 1. çeyrekteki yapay %75+ şut temposu düşüşe geçti.")
            send_telegram_message(msg)
        elif status == "Q2" and (a_q1 - h_q1 >= 9):
            msg = (f"🏀 **BASKETBOL ALARMI (HANDİKAP FIRSATI)** 🏀\n\n"
                   f"⚔️ **Maç:** {home_name} - {away_name}\n"
                   f"🏆 **Lig:** {item.get('league', {}).get('name')}\n"
                   f"⏱️ **Periyot:** 2. Çeyrek | Skor: {total_score}\n\n"
                   f"💡 **TAVSİYE BAHİS:** {home_name} **+ Handikap** veya **Galibiyet**\n"
                   f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55 Bandı\n"
                   f"📌 **Sebep:** Ev sahibi maça soğuk başladı, canlı handikap avantajlı noktada.")
            send_telegram_message(msg)

def check_live_football():
    if not API_KEY: return
    url = "https://v3.football.api-sports.io/fixtures?live=all"
    headers = {"x-apisports-key": API_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200: return
        data = res.json()
    except Exception: return

    if "response" not in data or not data["response"]: return

    for item in data["response"]:
        fixture = item.get("fixture", {})
        elapsed = fixture.get("status", {}).get("elapsed", 0) or 0
        league_name = item.get("league", {}).get("name", "").lower()
        if any(kw in league_name for kw in SKIP_FOOTBALL_LEAGUES): continue

        events = item.get("events", [])
        if any(e.get("type") == "Card" and e.get("detail") == "Red Card" for e in events if isinstance(e, dict)): continue

        teams = item.get("teams", {})
        home_team = teams.get("home", {}).get("name", "Ev")
        away_team = teams.get("away", {}).get("name", "Deplasman")
        stats = item.get("statistics", [])

        def get_stat(stat_list, name):
            for s in stat_list:
                if s.get("type") == name:
                    v = s.get("value")
                    return int(v) if v is not None and str(v).isdigit() else 0
            return 0

        if len(stats) >= 2:
            total_shots = get_stat(stats[0].get("statistics", []), "Total Shots") + get_stat(stats[1].get("statistics", []), "Total Shots")
            total_corners = get_stat(stats[0].get("statistics", []), "Corner Kicks") + get_stat(stats[1].get("statistics", []), "Corner Kicks")
        else:
            total_shots, total_corners = 4, 2

        if (15 <= elapsed <= 38) and (total_corners >= 2) and (total_shots >= 3):
            target_line = total_corners + 1.5
            msg = (f"🚩 **FUTBOL İY KORNER ALARMI** 🚩\n\n"
                   f"⚽ **Maç:** {home_team} - {away_team}\n"
                   f"🏆 **Lig:** {item.get('league', {}).get('name')}\n"
                   f"⏱️ **Dakika:** {elapsed}' (1. Yarı)\n\n"
                   f"📊 **Mevcut Korner:** {total_corners}\n"
                   f"💡 **TAVSİYE BAHİS:** İY **{target_line} Üst** Korner\n"
                   f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55")
            send_telegram_message(msg)

if __name__ == "__main__":
    check_live_football()
    check_live_basketball()
