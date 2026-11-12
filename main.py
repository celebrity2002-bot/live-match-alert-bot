import os
import requests
import re

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9"
}

SKIP_LEAGUES = [
    "women", "wom", "femenil", "femminile", "frauen", "feminine", "wnba",
    "u17", "u18", "u19", "u20", "u21", "u23", "youth", "junior", "academy",
    "reserves", "3x3", "friendly", "club friendlies"
]

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
    if not display_clock:
        return 0
    match = re.search(r"(\d+)", str(display_clock))
    return int(match.group(1)) if match else 0

def parse_remaining_seconds(display_clock):
    """Basketbol saatinden kalan süreyi saniye cinsinden döner."""
    if not display_clock:
        return 999
    clock_str = str(display_clock).strip()
    if ":" in clock_str:
        parts = clock_str.split(":")
        try:
            mins = int(parts[0])
            secs = float(parts[1])
            return int(mins * 60 + secs)
        except ValueError:
            return 999
    try:
        return int(float(clock_str))
    except ValueError:
        return 999

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
    """ESPN dünya geneli canlı basketbol taraması (ALT, ÜST, Handikap, Taktik Faul ve Blowout)."""
    basketball_endpoints = [
        ("NBA", "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard", 54, 44),
        ("EuroLeague", "https://site.api.espn.com/apis/site/v2/sports/basketball/eur.euroleague/scoreboard", 45, 31),
        ("NCAA", "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard", 78, 56)
    ]
    
    for default_league, url, high_limit, low_limit in basketball_endpoints:
        try:
            res = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
            if res.status_code != 200:
                continue
            data = res.json()
        except Exception:
            continue

        league_name = data.get("leagues", [{}])[0].get("abbreviation", default_league)
        if any(kw in league_name.lower() for kw in SKIP_LEAGUES):
            continue

        for event in data.get("events", []):
            event_id = str(event.get("id", ""))
            status_obj = event.get("status", {})
            state = status_obj.get("type", {}).get("state", "")
            period = status_obj.get("period", 0)
            display_clock = status_obj.get("displayClock", "")

            if state != "in":
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
            score_diff = abs(home_total - away_total)

            # --- A) 2. VE 3. PERİYOT SİNYALLERİ (1. Bölüm Temposuna Göre) ---
            valid_mid_periods = [2] if default_league == "NCAA" else [2, 3]
            if period in valid_mid_periods:
                home_lines = home.get("linescores", [])
                away_lines = away.get("linescores", [])
                if home_lines and away_lines:
                    h_q1 = int(home_lines[0].get("value", 0) or 0)
                    a_q1 = int(away_lines[0].get("value", 0) or 0)
                    q1_total = h_q1 + a_q1
                    period_label = "1. Yarı" if default_league == "NCAA" else "1. Çeyrek"

                    if q1_total >= high_limit:
                        alert_key = f"bb_{event_id}_under"
                        msg = (f"🏀 **BASKETBOL ALARMI (ALT SİNYALİ)** 🏀\n\n"
                               f"⚔️ **Maç:** {home_name} - {away_name}\n"
                               f"🏆 **Lig:** {league_name}\n"
                               f"⏱️ **Bölüm:** {period}. Periyot | Toplam Skor: {total_score}\n"
                               f"📊 **{period_label} Skoru:** {h_q1} - {a_q1} ({q1_total} Sayı)\n\n"
                               f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ALT**\n"
                               f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55 Bandı\n"
                               f"📌 **Sebep:** İlk bölümdeki yüksek şut temposu düşüş eğiliminde.")
                        send_telegram_message(alert_key, msg)

                    elif 0 < q1_total <= low_limit:
                        alert_key = f"bb_{event_id}_over"
                        msg = (f"🏀 **BASKETBOL ALARMI (ÜST SİNYALİ)** 🏀\n\n"
                               f"⚔️ **Maç:** {home_name} - {away_name}\n"
                               f"🏆 **Lig:** {league_name}\n"
                               f"⏱️ **Bölüm:** {period}. Periyot | Toplam Skor: {total_score}\n"
                               f"📊 **{period_label} Skoru:** {h_q1} - {a_q1} ({q1_total} Sayı)\n\n"
                               f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ÜST**\n"
                               f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55 Bandı\n"
                               f"📌 **Sebep:** İlk bölümdeki kısır skor sonrası canlı barem avantajlı indi.")
                        send_telegram_message(alert_key, msg)

                    if period == 2 and (a_q1 - h_q1 >= 9):
                        alert_key = f"bb_{event_id}_hcp"
                        msg = (f"🏀 **BASKETBOL ALARMI (HANDİKAP FIRSATI)** 🏀\n\n"
                               f"⚔️ **Maç:** {home_name} - {away_name}\n"
                               f"🏆 **Lig:** {league_name}\n"
                               f"⏱️ **Bölüm:** 2. Periyot | Skor: {home_total} - {away_total}\n\n"
                               f"💡 **TAVSİYE BAHİS:** {home_name} **+ Handikap** veya **Galibiyet**\n"
                               f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55 Bandı\n"
                               f"📌 **Sebep:** Ev sahibi maça soğuk başladı, canlı handikap avantajlı.")
                        send_telegram_message(alert_key, msg)

            # --- B) SON PERİYOT SİNYALLERİ (Taktik Faul ÜST & Maç Koptu ALT) ---
            final_period = 2 if default_league == "NCAA" else 4
            if period == final_period:
                rem_secs = parse_remaining_seconds(display_clock)

                # 1. Taktik Faul ÜST: Son 4 dakikada (240 sn) fark 1-6 sayı arasındaysa
                if (45 <= rem_secs <= 240) and (1 <= score_diff <= 6):
                    alert_key = f"bb_{event_id}_foul_over"
                    msg = (f"🔥 **BASKETBOL SON DAKİKA (TAKTİK FAUL ÜST)** 🔥\n\n"
                           f"⚔️ **Maç:** {home_name} - {away_name}\n"
                           f"🏆 **Lig:** {league_name}\n"
                           f"⏱️ **Süre:** Son Periyot {display_clock} | Skor: {home_total} - {away_total}\n\n"
                           f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ÜST**\n"
                           f"🎯 **Bilyoner Target Oranı:** 1.50 - 1.75 Bandı\n"
                           f"📌 **Sebep:** Başa baş giden maçta son dakikalarda taktik faullerle saat durup serbest atışlarla sayı yağacak.")
                    send_telegram_message(alert_key, msg)

                # 2. Maç Koptu (Blowout) ALT: Son periyotta fark 22+ sayı ise yedekler oyuna girer
                elif (rem_secs >= 240) and (score_diff >= 22):
                    alert_key = f"bb_{event_id}_blowout_under"
                    msg = (f"❄️ **BASKETBOL RÖLANTİ ALARMI (BLOWOUT ALT)** ❄️\n\n"
                           f"⚔️ **Maç:** {home_name} - {away_name}\n"
                           f"🏆 **Lig:** {league_name}\n"
                           f"⏱️ **Süre:** Son Periyot {display_clock} | Skor: {home_total} - {away_total}\n\n"
                           f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ALT**\n"
                           f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.60 Bandı\n"
                           f"📌 **Sebep:** Fark {score_diff} sayıya çıktı, as oyuncular dinlenmeye çekilip tempo düşecek.")
                    send_telegram_message(alert_
