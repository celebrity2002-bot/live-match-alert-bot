import os
import requests
import time
import re

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ESPN sunucularının isteği normal bir tarayıcı ziyareti olarak görmesi için kimlik başlığı
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9"
}

# Amatör, gençlik ve kadın liglerini elemek için filtreler
SKIP_LEAGUES = [
    "women", "wom", "femenil", "femminile", "frauen", "feminine", "wnba",
    "u17", "u18", "u19", "u20", "u21", "u23", "youth", "junior", "academy",
    "reserves", "3x3", "friendly", "club friendlies"
]

# Aynı çalışma döngüsünde aynı maça tekrar mesaj atmamak için hafıza
sent_alerts = set()

def send_telegram_message(alert_id, message):
    if alert_id in sent_alerts:
        return
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Token veya Chat ID eksik!")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            sent_alerts.add(alert_id)
    except Exception as e:
        print(f"Telegram hatasi: {e}")

def parse_minute(display_clock):
    """ESPN displayClock bilgisinden dakikayı tam sayı olarak çeker."""
    if not display_clock:
        return 0
    match = re.search(r"(\d+)", str(display_clock))
    return int(match.group(1)) if match else 0

def check_live_football():
    """ESPN dünya geneli + Türkiye Süper Lig canlı maç taraması."""
    football_endpoints = [
        "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/soccer/tur.1/scoreboard"
    ]

    for url in football_endpoints:
        try:
            res = requests.get(url, headers=BROWSER_HEADERS, timeout=12)
            if res.status_code != 200:
                print(f"ESPN Futbol yanit kodu ({url}): {res.status_code}")
                continue
            data = res.json()
        except Exception as e:
            print(f"Futbol baglanti hatasi: {e}")
            continue

        for event in data.get("events", []):
            event_id = str(event.get("id", ""))
            status_obj = event.get("status", {})
            state = status_obj.get("type", {}).get("state", "")
            period = status_obj.get("period", 0)

            # Sadece canlı maçları (state == 'in') ve 1. yarıyı (period == 1) kontrol et
            if state != "in" or period != 1:
                continue

            league_info = event.get("season", {}).get("slug", "") or ""
            event_name = event.get("name", "")
            comp_list = event.get("competitions", [])
            if not comp_list:
                continue

            comp = comp_list[0]
            league_title = comp.get("league", {}).get("name", "") or league_info
            check_text = f"{league_title} {league_info} {event_name}".lower()

            if any(kw in check_text for kw in SKIP_LEAGUES):
                continue

            minute = parse_minute(status_obj.get("displayClock", ""))
            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                continue

            home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
            away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

            home_name = home.get("team", {}).get("shortDisplayName", "Ev")
            away_name = away.get("team", {}).get("shortDisplayName", "Deplasman")

            h_goals = int(home.get("score", 0) or 0)
            a_goals = int(away.get("score", 0) or 0)
            total_goals = h_goals + a_goals

            # 1. Yarı 18-36. dakikalar arası 0-0 devam eden maçlarda İY 0.5 Üst sinyali
            if (18 <= minute <= 36) and total_goals == 0:
                alert_key = f"fb_{event_id}_iy05"
                msg = (f"⚽ **FUTBOL İY GOL FIRSATI** ⚽\n\n"
                       f"⚔️ **Maç:** {home_name} - {away_name}\n"
                       f"🏆 **Lig:** {league_title if league_title else 'Dünya Ligi'}\n"
                       f"⏱️ **Dakika:** {minute}' (Skor: {h_goals}-{a_goals})\n\n"
                       f"💡 **TAVSİYE BAHİS:** İlk Yarı **0.5 Üst** Gol\n"
                       f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.65 Bandı")
                send_telegram_message(alert_key, msg)

def check_live_basketball():
    """ESPN dünya geneli canlı basketbol taraması (NBA, EuroLeague, NCAA)."""
    basketball_endpoints = [
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/basketball/eur.euroleague/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
    ]
    
    for url in basketball_endpoints:
        try:
            res = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
            if res.status_code != 200:
                continue
            data = res.json()
        except Exception:
            continue

        league_name = data.get("leagues", [{}])[0].get("abbreviation", "Basketbol")
        if any(kw in league_name.lower() for kw in SKIP_LEAGUES):
            continue

        for event in data.get("events", []):
            event_id = str(event.get("id", ""))
            status_obj = event.get("status", {})
            state = status_obj.get("type", {}).get("state", "")
            period = status_obj.get("period", 0)

            # Sadece canlı maçları ve 2. veya 3. çeyreği kontrol et
            if state != "in" or period not in [2, 3]:
                continue

            competitions = event.get("competitions", [])
            if not competitions:
                continue

            competitors = competitions[0].get("competitors", [])
            if len(competitors) < 2:
                continue

            home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
            away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

            home_name = home.get("team", {}).get("shortDisplayName", "Ev")
            away_name = away.get("team", {}).get("shortDisplayName", "Deplasman")

            home_total = int(home.get("score", 0) or 0)
            away_total = int(away.get("score", 0) or 0)
            total_score = home_total + away_total

            home_lines = home.get("linescores", [])
            away_lines = away.get("linescores", [])
            if not home_lines or not away_lines:
                continue

            h_q1 = int(home_lines[0].get("value", 0) or 0)
            a_q1 = int(away_lines[0].get("value", 0) or 0)
            q1_total = h_q1 + a_q1

            if period in [2, 3] and q1_total >= 54:
                alert_key = f"bb_{event_id}_under"
                msg = (f"🏀 **BASKETBOL ALARMI (ALT SİNYALİ)** 🏀\n\n"
                       f"⚔️ **Maç:** {home_name} - {away_name}\n"
                       f"🏆 **Lig:** {league_name}\n"
                       f"⏱️ **Periyot:** {period}. Çeyrek | Toplam Skor: {total_score}\n"
                       f"📊 **1. Çeyrek Skoru:** {h_q1} - {a_q1} ({q1_total} Sayı)\n\n"
                       f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ALT**\n"
                       f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55 Bandı\n"
                       f"📌 **Sebep:** 1. çeyrekteki yüksek şut temposu düşüş eğiliminde.")
                send_telegram_message(alert_key, msg)

            elif period == 2 and (a_q1 - h_q1 >= 9):
                alert_key = f"bb_{event_id}_hcp"
                msg = (f"🏀 **BASKETBOL ALARMI (HANDİKAP FIRSATI)** 🏀\n\n"
                       f"⚔️ **Maç:** {home_name} - {away_name}\n"
                       f"🏆 **Lig:** {league_name}\n"
                       f"⏱️ **Periyot:** 2. Çeyrek | Skor: {home_total} - {away_total}\n\n"
                       f"💡 **TAVSİYE BAHİS:** {home_name} **+ Handikap** veya **Galibiyet**\n"
                       f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55 Bandı\n"
                       f"📌 **Sebep:** Ev sahibi maça soğuk başladı, canlı handikap avantajlı noktada.")
                send_telegram_message(alert_key, msg)

if __name__ == "__main__":
    print("Canli mac tarama botu baslatildi (ESPN Tam Dunya Kapsami)...")
    for cycle in range(4):
        check_live_football()
        check_live_basketball()
        if cycle < 3:
            time.sleep(60)
    print("Tarama dongusu basariyla tamamlandi.")
