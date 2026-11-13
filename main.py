import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("CHAT_ID")

# Başlangıç kasanı buradan değiştirebilirsin; bot tüm bahis tutarlarını otomatik hesaplar
KASA_TUTARI = 2000

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9"
}

# Bilyoner (İddaa) bülteninde düzenli canlı bahis açılan ligler ve milli maçlar
BILYONER_SOCCER_LEAGUES = [
    # Türkiye
    "tur.1", "tur.2",
    # İngiltere
    "eng.1", "eng.2", "eng.fa", "eng.league_cup",
    # İspanya
    "esp.1", "esp.2", "esp.copa_del_rey",
    # İtalya
    "ita.1", "ita.2", "ita.coppa_italia",
    # Almanya
    "ger.1", "ger.2", "ger.dfb_pokal",
    # Fransa
    "fra.1", "fra.2", "fra.coupe_de_france",
    # Diğer Avrupa Üst Ligleri
    "ned.1", "por.1", "bel.1", "sco.1",
    "aut.1", "sui.1", "gre.1", "den.1", "swe.1", "nor.1",
    # UEFA & Milli Maçlar
    "uefa.champions", "uefa.europa", "uefa.europa.conf",
    "uefa.nations", "fifa.worldq.uefa", "fifa.friendly",
    # İddaa Bültenindeki Seçili Dünya Ligleri
    "bra.1", "arg.1", "usa.1", "mex.1", "ksa.1"
]

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
        return 9999
    clock_str = str(display_clock).strip()
    if ":" in clock_str:
        parts = clock_str.split(":")
        try:
            mins = int(parts[0])
            secs = float(parts[1])
            return int(mins * 60 + secs)
        except ValueError:
            return 9999
    try:
        return int(float(clock_str))
    except ValueError:
        return 9999


def get_match_odds_info(comp):
    """ESPN maç önü handikap ve favori bilgisini okur."""
    odds_list = comp.get("odds") or []
    if not odds_list:
        return False, False, False, None, ""

    primary = odds_list[0] or {}
    details_str = str(primary.get("details", "")).strip()
    home_odds = primary.get("homeTeamOdds") or {}
    away_odds = primary.get("awayTeamOdds") or {}

    home_fav = bool(home_odds.get("favorite", False))
    away_fav = bool(away_odds.get("favorite", False))

    spread_val = None
    raw_spread = primary.get("spread")
    if raw_spread is not None:
        try:
            spread_val = float(raw_spread)
            if spread_val < 0:
                home_fav = True
            elif spread_val > 0:
                away_fav = True
        except (ValueError, TypeError):
            spread_val = None

    return True, home_fav, away_fav, spread_val, details_str


def extract_stats_from_list(stats_list):
    corners = 0
    sot = 0
    red_cards = 0
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
        elif "redcard" in name:
            red_cards += val
            found = True
    return corners, sot, red_cards, found


def get_soccer_live_metrics(league_slug, event_id, comp, competitors):
    total_corners = 0
    total_sot = 0
    total_reds = 0
    stats_found = False

    # Maç olaylarından (details) kırmızı kart kontrolü
    detail_reds = 0
    for det in comp.get("details") or []:
        det_type = str((det.get("type") or {}).get("text", "")).lower()
        if det.get("redCard") is True or "red card" in det_type:
            detail_reds += 1

    for comp_team in competitors:
        c, s, r, f = extract_stats_from_list(comp_team.get("statistics", []))
        total_corners += c
        total_sot += s
        total_reds += r
        if f:
            stats_found = True

    if stats_found:
        return total_corners, total_sot, max(total_reds, detail_reds), True

    summary_urls = [
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_slug}/summary?event={event_id}",
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary?event={event_id}"
    ]
    for summary_url in summary_urls:
        try:
            res = requests.get(summary_url, headers=BROWSER_HEADERS, timeout=6)
            if res.status_code == 200:
                s_data = res.json()
                for team_box in (s_data.get("boxscore") or {}).get("teams", []):
                    c, s, r, f = extract_stats_from_list(team_box.get("statistics", []))
                    total_corners += c
                    total_sot += s
                    total_reds += r
                    if f:
                        stats_found = True
                if stats_found:
                    break
        except Exception:
            continue

    return total_corners, total_sot, max(total_reds, detail_reds), stats_found


def fetch_league_events(league_slug):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_slug}/scoreboard"
    try:
        res = requests.get(url, headers=BROWSER_HEADERS, timeout=8)
        if res.status_code != 200:
            return []
        data = res.json()
        leagues_list = data.get("leagues") or [{}]
        league_name = leagues_list[0].get("name", league_slug)
        return [(league_slug, league_name, ev) for ev in data.get("events", [])]
    except Exception:
        return []


def check_live_football():
    seen_live_ids = set()
    all_events = []

    stake_high = int(KASA_TUTARI * 0.10)  # 2 Birim (200 TL)
    stake_std = int(KASA_TUTARI * 0.075)  # 1.5 Birim (150 TL)

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_league_events, BILYONER_SOCCER_LEAGUES)
        for batch in results:
            all_events.extend(batch)

    for league_slug, league_title, event in all_events:
        event_id = str(event.get("id", ""))
        if not event_id or event_id in seen_live_ids:
            continue

        status_obj = event.get("status", {})
        state = status_obj.get("type", {}).get("state", "")
        period = status_obj.get("period", 0)

        if state != "in":
            continue

        seen_live_ids.add(event_id)

        comp_list = event.get("competitions", [])
        if not comp_list:
            continue

        comp = comp_list[0]
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

        has_odds, home_fav, away_fav, _, odds_details = get_match_odds_info(comp)
        fav_tag = f" | Favori: {odds_details}" if (has_odds and odds_details) else ""

        # KURAL 1: İlk Yarı 18-22. Dakika Arası 0-0 + Canlı Baskı Filtresi (Tek Atış)
        if period == 1 and (18 <= minute <= 22) and total_goals == 0:
            corners, sot, _, has_stats = get_soccer_live_metrics(league_slug, event_id, comp, competitors)
            if has_stats and (corners >= 3 or sot >= 2) and (corners + sot >= 4):
                alert_key = f"fb_{event_id}_iy05"
                msg = (
                    f"⚽ **FUTBOL İY GOL FIRSATI** ⚽\n\n"
                    f"⚔️ **Maç:** {home_name} - {away_name}\n"
                    f"🏆 **Lig:** {league_title}{fav_tag}\n"
                    f"⏱️ **Dakika:** {minute}' (Skor: {h_goals}-{a_goals})\n"
                    f"📊 **Canlı Baskı:** {corners} Korner | {sot} İsabetli Şut\n\n"
                    f"💡 **TAVSİYE BAHİS:** İlk Yarı **0.5 Üst** Gol\n"
                    f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.65 Bandı\n"
                    f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_std} TL** (1.5 Birim - Standart Güven)"
                )
                send_telegram_message(alert_key, msg)

        # KURAL 2: İkinci Yarı 60-64. Dakika Arası Kritik An + Baskı Filtresi
        elif period == 2 and (60 <= minute <= 64) and abs(h_goals - a_goals) <= 1:
            corners, sot, _, has_stats = get_soccer_live_metrics(league_slug, event_id, comp, competitors)
            if has_stats and (corners + sot >= 7):
                alert_key = f"fb_{event_id}_2h_late"
                msg = (
                    f"⚡ **FUTBOL 2. YARI KRİTİK AN (60-64')** ⚡\n\n"
                    f"⚔️ **Maç:** {home_name} - {away_name}\n"
                    f"🏆 **Lig:** {league_title}{fav_tag}\n"
                    f"⏱️ **Dakika:** {minute}' (Skor: {h_goals}-{a_goals})\n"
                    f"📊 **Canlı Baskı:** {corners} Korner | {sot} İsabetli Şut\n\n"
                    f"💡 **TAVSİYE BAHİS:** Sıradaki Gol / Canlı **ÜST** Fırsatı\n"
                    f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.70 Bandı\n"
                    f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_std} TL** (1.5 Birim - Standart Güven)"
                )
                send_telegram_message(alert_key, msg)

        # KURAL 3 (SNIPER): Kırmızı Kart + Baskı Radarı (68-73' Arası, 11'e 10 Avantajı)
        elif period == 2 and (68 <= minute <= 73):
            corners, sot, reds, has_stats = get_soccer_live_metrics(league_slug, event_id, comp, competitors)
            if has_stats and reds >= 1 and (corners + sot >= 8):
                alert_key = f"fb_{event_id}_redcard"
                msg = (
                    f"🟥 **SNIPER RADAR: KIRMIZI KART + BASKI** 🟥\n\n"
                    f"⚔️ **Maç:** {home_name} - {away_name}\n"
                    f"🏆 **Lig:** {league_title}\n"
                    f"⏱️ **Dakika:** {minute}' (Skor: {h_goals}-{a_goals} | Kırmızı Kart: {reds})\n"
                    f"📊 **Canlı Baskı:** {corners} Korner | {sot} İsabetli Şut\n\n"
                    f"💡 **TAVSİYE BAHİS:** Sıradaki Gol / Canlı **ÜST** Fırsatı\n"
                    f"🎯 **Bilyoner Target Oranı:** 1.50 - 1.75 Bandı\n"
                    f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_high} TL** (2 Birim - Yüksek Güven)"
                )
                send_telegram_message(alert_key, msg)

        # KURAL 4 (SNIPER): "Son Kale" Geç Gol Kuralı (75-80' Arası, Yoğun Baskı >= 11)
        elif period == 2 and (75 <= minute <= 80) and abs(h_goals - a_goals) <= 1:
            corners, sot, _, has_stats = get_soccer_live_metrics(league_slug, event_id, comp, competitors)
            if has_stats and (corners + sot >= 11):
                alert_key = f"fb_{event_id}_sonkale"
                msg = (
                    f"🔥 **FUTBOL SON KALE (75-80' GEÇ GOL)** 🔥\n\n"
                    f"⚔️ **Maç:** {home_name} - {away_name}\n"
                    f"🏆 **Lig:** {league_title}{fav_tag}\n"
                    f"⏱️ **Dakika:** {minute}' (Skor: {h_goals}-{a_goals})\n"
                    f"📊 **Yoğun Baskı:** {corners} Korner | {sot} İsabetli Şut\n\n"
                    f"💡 **TAVSİYE BAHİS:** Canlı **ÜST** / Sıradaki Gol\n"
                    f"🎯 **Bilyoner Target Oranı:** 1.55 - 1.85 Bandı\n"
                    f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_std} TL** (1.5 Birim - Standart Güven)"
                )
                send_telegram_message(alert_key, msg)

    return len(seen_live_ids)


def check_live_basketball():
    now_us_east = datetime.now(timezone.utc) - timedelta(hours=5)
    us_dates = [now_us_east.strftime("%Y%m%d")]
    if now_us_east.hour < 5:
        us_dates.append((now_us_east - timedelta(days=1)).strftime("%Y%m%d"))

    stake_high = int(KASA_TUTARI * 0.10)  # 2 Birim (200 TL)
    stake_low = int(KASA_TUTARI * 0.05)   # 1 Birim (100 TL)

    # 4 dakikalık kilitli 2. periyot pencereleri (Tek bildirim garantisi)
    basketball_endpoints = [
        ("EuroLeague", "https://site.api.espn.com/apis/site/v2/sports/basketball/eur.euroleague/scoreboard", 50, 30, 600, 360),
        ("FIBA", "https://site.api.espn.com/apis/site/v2/sports/basketball/fiba/scoreboard", 50, 30, 600, 360)
    ]
    for d_str in us_dates:
        basketball_endpoints.append(
            ("NBA", f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d_str}", 66, 43, 720, 480)
        )
        basketball_endpoints.append(
            ("NCAA", f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates={d_str}", 84, 54, 1200, 960)
        )

    seen_live_ids = set()

    for default_league, url, high_limit, low_limit, p2_start_sec, p2_end_sec in basketball_endpoints:
        try:
            res = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
            if res.status_code != 200:
                continue
            data = res.json()
        except Exception:
            continue

        leagues_list = data.get("leagues") or [{}]
        league_name = leagues_list[0].get("abbreviation", default_league)
        if any(kw in league_name.lower() for kw in SKIP_LEAGUES):
            continue

        for event in data.get("events", []):
            event_id = str(event.get("id", ""))
            if not event_id or event_id in seen_live_ids:
                continue

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

            comp = competitions[0]
            competitors = comp.get("competitors", [])
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
            rem_secs = parse_remaining_seconds(display_clock)

            has_odds, home_fav, away_fav, spread_val, odds_details = get_match_odds_info(comp)

            # SADECE 2. PERİYOT İLK 4 DAKİKA PENCERESİ
            if period == 2 and (p2_end_sec <= rem_secs <= p2_start_sec):
                home_lines = home.get("linescores", [])
                away_lines = away.get("linescores", [])
                if home_lines and away_lines:
                    h_q1 = int(home_lines[0].get("value", 0) or 0)
                    a_q1 = int(away_lines[0].get("value", 0) or 0)
                    q1_total = h_q1 + a_q1
                    q1_diff = abs(h_q1 - a_q1)
                    period_label = "1. Yarı" if default_league == "NCAA" else "1. Çeyrek"

                    # KURAL 1: Tempo Regresyonu ALT
                    if q1_total >= high_limit and q1_diff >= 5:
                        alert_key = f"bb_{event_id}_under"
                        msg = (
                            f"🏀 **BASKETBOL ALARMI (TEMPO DÜŞÜŞÜ ALT)** 🏀\n\n"
                            f"⚔️ **Maç:** {home_name} - {away_name}\n"
                            f"🏆 **Lig:** {league_name}\n"
                            f"⏱️ **Süre:** 2. Periyot {display_clock} | Toplam Skor: {total_score}\n"
                            f"📊 **{period_label} Skoru:** {h_q1} - {a_q1} ({q1_total} Sayı)\n\n"
                            f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ALT**\n"
                            f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55 Bandı\n"
                            f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_low} TL** (1 Birim - Kontrollü Test)\n"
                            f"📌 **Sebep:** İlk bölümdeki ekstrem şut yüzdesi ve fark sonrası tempo dengelenecek."
                        )
                        send_telegram_message(alert_key, msg)

                    # KURAL 2: Düşük Barem ÜST
                    elif 0 < q1_total <= low_limit:
                        alert_key = f"bb_{event_id}_over"
                        msg = (
                            f"🏀 **BASKETBOL ALARMI (DÜŞÜK BAREM ÜST)** 🏀\n\n"
                            f"⚔️ **Maç:** {home_name} - {away_name}\n"
                            f"🏆 **Lig:** {league_name}\n"
                            f"⏱️ **Süre:** 2. Periyot {display_clock} | Toplam Skor: {total_score}\n"
                            f"📊 **{period_label} Skoru:** {h_q1} - {a_q1} ({q1_total} Sayı)\n\n"
                            f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ÜST**\n"
                            f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55 Bandı\n"
                            f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_low} TL** (1 Birim - Kontrollü Test)\n"
                            f"📌 **Sebep:** İlk bölümdeki kısır skor sonrası canlı barem avantajlı indi."
                        )
                        send_telegram_message(alert_key, msg)

                    # KURAL 3 (SNIPER): Maç Önü Favorisi Ev Sahibi Geri Dönüş Handikapı
                    is_valid_fav = (not has_odds) or (home_fav and not away_fav and (spread_val is None or spread_val <= -2.5))
                    if is_valid_fav and (a_q1 - h_q1 >= 9) and (home_total - away_total >= -14):
                        fav_note = f" (Maç Önü: {odds_details})" if odds_details else ""
                        alert_key = f"bb_{event_id}_hcp"
                        msg = (
                            f"🏀 **SNIPER: FAVORİ EV SAHİBİ HANDİKAP** 🏀\n\n"
                            f"⚔️ **Maç:** {home_name} - {away_name}{fav_note}\n"
                            f"🏆 **Lig:** {league_name}\n"
                            f"⏱️ **Süre:** 2. Periyot {display_clock} | Skor: {home_total} - {away_total}\n"
                            f"📊 **{period_label} Skoru:** {h_q1} - {a_q1}\n\n"
                            f"💡 **TAVSİYE BAHİS:** {home_name} **+ Handikap** veya **Galibiyet**\n"
                            f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.70 Bandı\n"
                            f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_high} TL** (2 Birim - Yüksek Güven)\n"
                            f"📌 **Sebep:** Maç önü favorisi ev sahibi ilk bölümü geride kapattı, geri dönüş bandında."
                        )
                        send_telegram_message(alert_key, msg)

            # SON PERİYOT STRATEJİLERİ
            final_period = 2 if default_league == "NCAA" else 4
            if period == final_period:
                # KURAL 4 (SNIPER): Keskin Taktik Faul ÜST (02:30 - 00:40 arası, 1-5 sayı fark)
                if (40 <= rem_secs <= 150) and (1 <= score_diff <= 5):
                    alert_key = f"bb_{event_id}_foul_over"
                    msg = (
                        f"🔥 **SNIPER SON DAKİKA (TAKTİK FAUL ÜST)** 🔥\n\n"
                        f"⚔️ **Maç:** {home_name} - {away_name}\n"
                        f"🏆 **Lig:** {league_name}\n"
                        f"⏱️ **Süre:** Son Periyot {display_clock} | Skor: {home_total} - {away_total}\n\n"
                        f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ÜST**\n"
                        f"🎯 **Bilyoner Target Oranı:** 1.50 - 1.75 Bandı\n"
                        f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_high} TL** (2 Birim - Yüksek Güven)\n"
                        f"📌 **Sebep:** Son 2.5 dakikada {score_diff} sayı farkla taktik fauller ve serbest atışlar zorunlu hale geldi."
                    )
                    send_telegram_message(alert_key, msg)

                # KURAL 5: Fark Açılınca Rölanti ALT (08:30 - 05:00 arası, >= 20 sayı fark)
                elif (300 <= rem_secs <= 510) and (score_diff >= 20):
                    alert_key = f"bb_{event_id}_blowout_under"
                    msg = (
                        f"❄️ **BASKETBOL RÖLANTİ ALARMI (FARK AÇILDI ALT)** ❄️\n\n"
                        f"⚔️ **Maç:** {home_name} - {away_name}\n"
                        f"🏆 **Lig:** {league_name}\n"
                        f"⏱️ **Süre:** Son Periyot {display_clock} | Skor: {home_total} - {away_total}\n\n"
                        f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ALT**\n"
                        f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.60 Bandı\n"
                        f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_low} TL** (1 Birim - Kontrollü Test)\n"
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
            f"🏀 Taranan Canlı Basketbol: **{live_bb}** maç\n"
            f"💼 Aktif Kasa: **{KASA_TUTARI} TL** (1 Birim: {int(KASA_TUTARI * 0.05)} TL)"
        )
        send_telegram_message("hourly_status", status_msg)
