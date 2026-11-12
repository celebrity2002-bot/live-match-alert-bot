import os
import re
from datetime import datetime, timezone
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("CHAT_ID")

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9"
}

# Sadece 3x3 basketbolu eler; Bilyoner'deki U19, U21 ve hazırlık maçlarını engellemez
SKIP_LEAGUES = ["3x3"]

sent_alerts = set()


def send_telegram_message(alert_id, message):
    if alert_id in sent_alerts:
        return
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Token veya Chat ID eksik!")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            sent_alerts.add(alert_id)
        else:
            print(f"Telegram yanit kodu: {res.status_code}")
    except Exception as e:
        print(f"Telegram hatasi: {e}")


def parse_minute(display_clock):
    if not display_clock:
        return 0
    match = re.search(r"(\d+)", str(display_clock))
    return int(match.group(1)) if match else 0


def parse_remaining_seconds(display_clock):
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


def extract_stats_from_list(stats_list):
    corners = 0
    sot = 0
    found = False
    for item in stats_list or []:
        name = str(item.get("name", "")).lower()
        val_str = str(item.get("displayValue", "0")).strip()
        try:
            val = int(float(val_str))
        except ValueError:
            val = 0
        if "corner" in name:
            corners += val
            found = True
        elif "shotsontarget" in name or "shotontarget" in name:
            sot += val
            found = True
    return corners, sot, found


def get_soccer_pressure(event_id, competitors):
    total_corners = 0
    total_sot = 0
    stats_found = False

    for comp in competitors:
        c, s, f = extract_stats_from_list(comp.get("statistics", []))
        total_corners += c
        total_sot += s
        if f:
            stats_found = True

    if stats_found:
        return total_corners, total_sot, True

    # Scoreboard özetinde istatistik yoksa maç detayından canlı veriyi çeker
    summary_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary?event={event_id}"
    try:
        res = requests.get(summary_url, headers=BROWSER_HEADERS, timeout=6)
        if res.status_code == 200:
            s_data = res.json()
            for team_box in s_data.get("boxscore", {}).get("teams", []):
                c, s, f = extract_stats_from_list(team_box.get("statistics", []))
                total_corners += c
                total_sot += s
                if f:
                    stats_found = True
    except Exception:
        pass

    return total_corners, total_sot, stats_found


def check_live_football():
    football_endpoints = [
        "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard",
        "https://site.api.espn.com/apis/site/v2/sports/soccer/tur.1/scoreboard"
    ]
    seen_live_ids = set()

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
            if not event_id or event_id in seen_live_ids:
                continue

            status_obj = event.get("status", {})
            state = status_obj.get("type", {}).get("state", "")
            period = status_obj.get("period", 0)

            if state != "in":
                continue

            seen_live_ids.add(event_id)

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

            # KURAL 1: İlk Yarı 18-30. Dakika Arası 0-0 + Canlı Baskı Filtresi
            if period == 1 and (18 <= minute <= 30) and total_goals == 0:
                corners, sot, has_stats = get_soccer_pressure(event_id, competitors)
                # En az 3 korner veya 2 isabetli şut (toplam baskı >= 4) şartı
                if has_stats and (corners >= 3 or sot >= 2) and (corners + sot >= 4):
                    alert_key = f"fb_{event_id}_iy05"
                    msg = (
                        f"⚽ **FUTBOL İY GOL FIRSATI** ⚽\n\n"
                        f"⚔️ **Maç:** {home_name} - {away_name}\n"
                        f"🏆 **Lig:** {league_title if league_title else 'Dünya Ligi'}\n"
                        f"⏱️ **Dakika:** {minute}' (Skor: {h_goals}-{a_goals})\n"
                        f"📊 **Canlı Baskı:** {corners} Korner | {sot} İsabetli Şut\n\n"
                        f"💡 **TAVSİYE BAHİS:** İlk Yarı **0.5 Üst** Gol\n"
                        f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.65 Bandı"
                    )
                    send_telegram_message(alert_key, msg)

            # KURAL 2: İkinci Yarı 60-65. Dakika Arası Berabere / Tek Farklı Kritik An + Baskı Filtresi
            elif period == 2 and (60 <= minute <= 65) and abs(h_goals - a_goals) <= 1:
                corners, sot, has_stats = get_soccer_pressure(event_id, competitors)
                if has_stats and (corners + sot >= 7):
                    alert_key = f"fb_{event_id}_2h_late"
                    msg = (
                        f"⚡ **FUTBOL 2. YARI KRİTİK AN (60-65')** ⚡\n\n"
                        f"⚔️ **Maç:** {home_name} - {away_name}\n"
                        f"🏆 **Lig:** {league_title if league_title else 'Dünya Ligi'}\n"
                        f"⏱️ **Dakika:** {minute}' (Skor: {h_goals}-{a_goals})\n"
                        f"📊 **Canlı Baskı:** {corners} Korner | {sot} İsabetli Şut\n\n"
                        f"💡 **TAVSİYE BAHİS:** Sıradaki Gol / Canlı **ÜST** Fırsatı\n"
                        f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.70 Bandı"
                    )
                    send_telegram_message(alert_key, msg)

    return len(seen_live_ids)


def check_live_basketball():
    basketball_endpoints = [
        ("NBA", "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard", 54, 44),
        ("EuroLeague", "https://site.api.espn.com/apis/site/v2/sports/basketball/eur.euroleague/scoreboard", 45, 31),
        ("NCAA", "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard", 78, 56),
        ("FIBA", "https://site.api.espn.com/apis/site/v2/sports/basketball/fiba/scoreboard", 45, 31)
    ]
    seen_live_ids = set()

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

            seen_live_ids.add(event_id)

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
                        msg = (
                            f"🏀 **BASKETBOL ALARMI (ALT SİNYALİ)** 🏀\n\n"
                            f"⚔️ **Maç:** {home_name} - {away_name}\n"
                            f"🏆 **Lig:** {league_name}\n"
                            f"⏱️ **Bölüm:** {period}. Periyot | Toplam Skor: {total_score}\n"
                            f"📊 **{period_label} Skoru:** {h_q1} - {a_q1} ({q1_total} Sayı)\n\n"
                            f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ALT**\n"
                            f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55 Bandı\n"
                            f"📌 **Sebep:** İlk bölümdeki yüksek şut temposu düşüş eğiliminde."
                        )
                        send_telegram_message(alert_key, msg)

                    elif 0 < q1_total <= low_limit:
                        alert_key = f"bb_{event_id}_over"
                        msg = (
                            f"🏀 **BASKETBOL ALARMI (ÜST SİNYALİ)** 🏀\n\n"
                            f"⚔️ **Maç:** {home_name} - {away_name}\n"
                            f"🏆 **Lig:** {league_name}\n"
                            f"⏱️ **Bölüm:** {period}. Periyot | Toplam Skor: {total_score}\n"
                            f"📊 **{period_label} Skoru:** {h_q1} - {a_q1} ({q1_total} Sayı)\n\n"
                            f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ÜST**\n"
                            f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55 Bandı\n"
                            f"📌 **Sebep:** İlk bölümdeki kısır skor sonrası canlı barem avantajlı indi."
                        )
                        send_telegram_message(alert_key, msg)

                    if period == 2 and (a_q1 - h_q1 >= 9):
                        alert_key = f"bb_{event_id}_hcp"
                        msg = (
                            f"🏀 **BASKETBOL ALARMI (HANDİKAP FIRSATI)** 🏀\n\n"
                            f"⚔️ **Maç:** {home_name} - {away_name}\n"
                            f"🏆 **Lig:** {league_name}\n"
                            f"⏱️ **Bölüm:** 2. Periyot | Skor: {home_total} - {away_total}\n\n"
                            f"💡 **TAVSİYE BAHİS:** {home_name} **+ Handikap** veya **Galibiyet**\n"
                            f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55 Bandı\n"
                            f"📌 **Sebep:** Ev sahibi maça soğuk başladı, canlı handikap avantajlı."
                        )
                        send_telegram_message(alert_key, msg)

            final_period = 2 if default_league == "NCAA" else 4
            if period == final_period:
                rem_secs = parse_remaining_seconds(display_clock)

                if (45 <= rem_secs <= 240) and (1 <= score_diff <= 6):
                    alert_key = f"bb_{event_id}_foul_over"
                    msg = (
                        f"🔥 **BASKETBOL SON DAKİKA (TAKTİK FAUL ÜST)** 🔥\n\n"
                        f"⚔️ **Maç:** {home_name} - {away_name}\n"
                        f"🏆 **Lig:** {league_name}\n"
                        f"⏱️ **Süre:** Son Periyot {display_clock} | Skor: {home_total} - {away_total}\n\n"
                        f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ÜST**\n"
                        f"🎯 **Bilyoner Target Oranı:** 1.50 - 1.75 Bandı\n"
                        f"📌 **Sebep:** Başa baş giden maçta son dakikalarda taktik faullerle saat durup serbest atışlarla sayı yağacak."
                    )
                    send_telegram_message(alert_key, msg)

                elif (rem_secs >= 240) and (score_diff >= 22):
                    alert_key = f"bb_{event_id}_blowout_under"
                    msg = (
                        f"❄️ **BASKETBOL RÖLANTİ ALARMI (BLOWOUT ALT)** ❄️\n\n"
                        f"⚔️ **Maç:** {home_name} - {away_name}\n"
                        f"🏆 **Lig:** {league_name}\n"
                        f"⏱️ **Süre:** Son Periyot {display_clock} | Skor: {home_total} - {away_total}\n\n"
                        f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ALT**\n"
                        f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.60 Bandı\n"
                        f"📌 **Sebep:** Fark {score_diff} sayıya çıktı, as oyuncular dinlenmeye çekilip tempo düşecek."
                    )
                    send_telegram_message(alert_key, msg)

    return len(seen_live_ids)


if __name__ == "__main__":
    print("Canli mac tarama botu baslatildi...")
    live_fb = check_live_football()
    live_bb = check_live_basketball()
    print(f"Tarama tamamlandi. Canli Futbol: {live_fb}, Canli Basketbol: {live_bb}")

    # Her saat başı (00-09. dakikalar arası) otomatik arka plan durum raporu gönderir
    now_utc = datetime.now(timezone.utc)
    if now_utc.minute < 10:
        status_msg = (
            f"🤖 **Otomatik Arka Plan Raporu**\n"
            f"⚽ Taranan Canlı Futbol: **{live_fb}** maç\n"
            f"🏀 Taranan Canlı Basketbol: **{live_bb}** maç"
        )
        send_telegram_message("hourly_status", status_msg)
