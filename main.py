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

# SADECE RESMİ VE ÜST DÜZEY LİGLER (Riski minimumda tutmak için hazırlık ve alt ligler hariç)
BILYONER_SOCCER_LEAGUES = [
    # Türkiye
    "tur.1", "tur.2", "tur.cup",
    # İngiltere
    "eng.1", "eng.2", "eng.3", "eng.fa", "eng.league_cup",
    # İspanya
    "esp.1", "esp.2", "esp.copa_del_rey",
    # İtalya
    "ita.1", "ita.2", "ita.coppa_italia",
    # Almanya
    "ger.1", "ger.2", "ger.dfb_pokal",
    # Fransa
    "fra.1", "fra.2", "fra.coupe_de_france",
    # Diğer Avrupa Üst & Golcü Ligleri
    "ned.1", "ned.2", "por.1", "bel.1", "sco.1",
    "aut.1", "sui.1", "gre.1", "den.1", "swe.1", "nor.1",
    "pol.1", "cze.1", "rou.1", "cro.1",
    # UEFA Resmi Organizasyonları & Milli Resmi Maçlar
    "uefa.champions", "uefa.europa", "uefa.europa.conf",
    "uefa.nations", "fifa.worldq.uefa",
    # Seçili Dünya & Amerika/Asya Ligleri
    "bra.1", "arg.1", "usa.1", "mex.1", "ksa.1",
    "aus.1", "jpn.1", "kor.1"
]

SKIP_LEAGUES = ["3x3", "women", "femenina", "kadın", "u18", "u19", "u20", "cyber", "esports", "friendly", "hazırlık"]

sent_alerts = set()
match_signaled_today = set()  # Aynı maçtan gün içinde tekrar sinyal gelmesini önleyen hafıza


def send_telegram_message(alert_id, message, match_id=None):
    if alert_id in sent_alerts:
        return
    if match_id and match_id in match_signaled_today:
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
            if match_id:
                match_signaled_today.add(match_id)
        else:
            print(f"Telegram yanit kodu: {res.status_code}")
    except Exception as e:
        print(f"Telegram hatasi: {e}")


def safe_int(val, default=0):
    if val is None or val == "":
        return default
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return default


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


def parse_team_stats(team_obj):
    corners = 0
    sot = 0
    reds = 0
    found = False
    for item in team_obj.get("statistics", []):
        name = str(item.get("name", "")).lower()
        val = safe_int(item.get("displayValue", 0))
        if "corner" in name:
            corners = val
            found = True
        elif "shotsontarget" in name or "shotontarget" in name:
            sot = val
            found = True
        elif "redcard" in name:
            reds = val
            found = True
    return corners, sot, reds, found


def get_soccer_live_metrics(league_slug, event_id, comp, competitors):
    """
    Çoklu Veri Kaynağı (Multi-Source Fallback): Ev sahibi ve deplasman korner, 
    isabetli şut ve kart verilerini ayrı ayrı kusursuz çeker.
    """
    home_corners, away_corners = 0, 0
    home_sot, away_sot = 0, 0
    total_reds = 0
    stats_found = False

    for comp_team in competitors:
        c, s, r, f = parse_team_stats(comp_team)
        is_home = comp_team.get("homeAway") == "home"
        if is_home:
            home_corners, home_sot = c, s
        else:
            away_corners, away_sot = c, s
        total_reds += r
        if f:
            stats_found = True

    if stats_found:
        return home_corners, away_corners, home_sot, away_sot, total_reds, True

    # Yedek Kaynak Katmanı (Fallback Endpoints)
    summary_urls = [
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_slug}/summary?event={event_id}",
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary?event={event_id}"
    ]
    for summary_url in summary_urls:
        try:
            res = requests.get(summary_url, headers=BROWSER_HEADERS, timeout=6)
            if res.status_code == 200:
                s_data = res.json()
                teams_box = (s_data.get("boxscore") or {}).get("teams", [])
                for tb in teams_box:
                    c, s, r, f = parse_team_stats(tb)
                    if tb.get("homeAway") == "home" or (tb.get("team", {}).get("homeAway") == "home"):
                        home_corners, home_sot = c, s
                    else:
                        away_corners, away_sot = c, s
                    total_reds += r
                    if f:
                        stats_found = True
                if stats_found:
                    break
        except Exception:
            continue

    return home_corners, away_corners, home_sot, away_sot, total_reds, stats_found


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

    stake_high = int(KASA_TUTARI * 0.10)  # 2 Birim (200 TL) - Yüksek Güven
    stake_std = int(KASA_TUTARI * 0.075)  # 1.5 Birim (150 TL) - Standart Güven

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = executor.map(fetch_league_events, BILYONER_SOCCER_LEAGUES)
        for batch in results:
            all_events.extend(batch)

    for league_slug, league_title, event in all_events:
        if any(w in league_title.lower() for w in ["friendly", "hazırlık", "exhibition"]):
            continue

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
        competitors = comp.get("competitions", [])
        if len(competitors) < 2:
            continue

        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        home_name = home.get("team", {}).get("shortDisplayName", "Ev")
        away_name = away.get("team", {}).get("shortDisplayName", "Deplasman")

        h_goals = safe_int(home.get("score", 0))
        a_goals = safe_int(away.get("score", 0))
        total_goals = h_goals + a_goals
        goal_diff = abs(h_goals - a_goals)

        has_odds, home_fav, away_fav, spread_val, odds_details = get_match_odds_info(comp)
        fav_tag = f" | Favori: {odds_details}" if (has_odds and odds_details) else ""

        # Metrikleri çek (Ev Korner, Deplasman Korner, SOT vb.)
        h_corners, a_corners, h_sot, a_sot, reds, has_stats = get_soccer_live_metrics(league_slug, event_id, comp, competitors)
        total_corners = h_corners + a_corners
        total_sot = h_sot + a_sot

        # Kural 1: İlk Yarı Erken Korner Patlaması (20-30. Dakika) -> Toplam Korner ÜST
        if period == 1 and (20 <= minute <= 30) and total_corners >= 4:
            alert_key = f"fb_{event_id}_iy_corner"
            msg = (
                f"⚽ **CANLI KORNER ALARMI (İLK YARI ÜST)** ⚽\n\n"
                f"⚔️ **Maç:** {home_name} - {away_name}\n"
                f"🏆 **Lig:** {league_title}{fav_tag}\n"
                f"⏱️ **Dakika:** {minute}' (Skor: {h_goals}-{a_goals})\n"
                f"📊 **Anlık Kornerler:** {home_name}: {h_corners} | {away_name}: {a_corners} (Toplam: **{total_corners}**)\n\n"
                f"💡 **TAVSİYE BAHİS:** Canlı Toplam Korner **ÜST** (Bilyoner Canlı Baremi)\n"
                f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.70 Bandı\n"
                f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_std} TL** (1.5 Birim)"
            )
            send_telegram_message(alert_key, msg, match_id=event_id)

        # Kural 2: 2. Yarı Kritik Toplam Korner Üst (65-78. Dakika - Skor Yakın, Baskı Yüksek)
        elif period == 2 and (65 <= minute <= 78) and goal_diff <= 1 and total_corners >= 8:
            alert_key = f"fb_{event_id}_2h_total_corner"
            msg = (
                f"⚡ **CANLI KORNER ALARMI (MAÇ SONU TOPLAM ÜST)** ⚡\n\n"
                f"⚔️ **Maç:** {home_name} - {away_name}\n"
                f"🏆 **Lig:** {league_title}{fav_tag}\n"
                f"⏱️ **Dakika:** {minute}' (Skor: {h_goals}-{a_goals})\n"
                f"📊 **Anlık Kornerler:** {home_name}: {h_corners} | {away_name}: {a_corners} (Toplam: **{total_corners}**)\n"
                f"🎯 **İsabetli Şut:** {total_sot}\n\n"
                f"💡 **TAVSİYE BAHİS:** Canlı Toplam Korner **ÜST**\n"
                f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.70 Bandı\n"
                f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_std} TL** (1.5 Birim)"
            )
            send_telegram_message(alert_key, msg, match_id=event_id)

        # Kural 3: Favori Ev Sahibi Takım Korner Baskısı (60-80. Dakika) -> Ev Sahibi Korner ÜST
        elif period == 2 and (60 <= minute <= 80) and has_odds and home_fav and not away_fav and (h_goals <= a_goals) and h_corners >= 6:
            alert_key = f"fb_{event_id}_home_corner"
            msg = (
                f"🎯 **SNIPER: EV SAHİBİ KORNER ÜST BASKISI** 🎯\n\n"
                f"⚔️ **Maç:** {home_name} - {away_name}\n"
                f"🏆 **Lig:** {league_title}{fav_tag}\n"
                f"⏱️ **Dakika:** {minute}' (Skor: {h_goals}-{a_goals})\n"
                f"📊 **Ev Sahibi Korner:** **{h_corners}** | Toplam Korner: {total_corners}\n\n"
                f"💡 **TAVSİYE BAHİS:** **{home_name} Korner ÜST** (Canlı Barem)\n"
                f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.75 Bandı\n"
                f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_high} TL** (2 Birim)"
            )
            send_telegram_message(alert_key, msg, match_id=event_id)

        # Kural 4: Son Kale / Maç Sonu Korner Patlaması (80-88. Dakika)
        elif period == 2 and (80 <= minute <= 88) and goal_diff <= 1 and total_corners >= 11:
            alert_key = f"fb_{event_id}_son_kale_corner"
            msg = (
                f"🔥 **FUTBOL SON KALE (SON DAKİKA KORNER ÜST)** 🔥\n\n"
                f"⚔️ **Maç:** {home_name} - {away_name}\n"
                f"🏆 **Lig:** {league_title}{fav_tag}\n"
                f"⏱️ **Dakika:** {minute}' (Skor: {h_goals}-{a_goals})\n"
                f"📊 **Anlık Toplam Korner:** **{total_corners}** ({home_name}: {h_corners} - {away_name}: {a_corners})\n\n"
                f"💡 **TAVSİYE BAHİS:** Canlı Toplam Korner **ÜST** (Kıl Payı Barem)\n"
                f"🎯 **Bilyoner Target Oranı:** 1.50 - 1.85 Bandı\n"
                f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_std} TL** (1.5 Birim)"
            )
            send_telegram_message(alert_key, msg, match_id=event_id)

    return len(seen_live_ids)


def classify_world_league(country_raw, league_raw):
    country = str(country_raw or "").lower()
    league = str(league_raw or "").lower()
    combined = f"{country} {league}"

    if any(bad in combined for bad in SKIP_LEAGUES):
        return None, 50, 30

    if ("korea" in country) and ("kbl" in league) and ("wkbl" not in league):
        return "Güney Kore KBL", 50, 29
    if ("japan" in country) and ("b.league" in league or "b1" in league) and ("b2" not in league) and ("b3" not in league):
        return "Japonya B.League", 51, 30
    if ("turkey" in country or "türkiye" in country) and ("super" in league or "süper" in league or "bsl" in league) and ("kbsl" not in league):
        return "Türkiye BSL", 50, 30
    if ("spain" in country) and ("acb" in league or "liga endesa" in league):
        return "İspanya ACB", 51, 30
    if ("italy" in country) and ("lega a" in league or "serie a" in league or "lba" in league) and ("a2" not in league):
        return "İtalya LBA", 50, 30
    if ("germany" in country) and ("bbl" in league or "bundesliga" in league) and ("pro a" not in league) and ("pro b" not in league):
        return "Almanya BBL", 51, 30
    if ("france" in country) and ("lnb" in league or "pro a" in league or "betclic" in league) and ("pro b" not in league):
        return "Fransa LNB", 50, 30
    if ("eurocup" in league) and ("euroleague" not in league):
        return "EuroCup", 51, 30
    if ("champions league" in league) and ("americas" not in league) and ("asia" not in league):
        return "FIBA Şampiyonlar Ligi", 50, 30
    if ("aba" in league) and ("2" not in league) and ("liga" in league or "league" in league):
        return "Adriyatik ABA Ligi", 50, 30

    return None, 50, 30


def fetch_world_basketball_games():
    normalized_games = []
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    ls_headers = {
        **BROWSER_HEADERS,
        "Origin": "https://www.livescore.com",
        "Referer": "https://www.livescore.com/"
    }
    ls_urls = [
        "https://prod-public-api.livescore.com/v1/api/app/live/basketball/3?MD=1",
        f"https://prod-public-api.livescore.com/v1/api/app/date/basketball/{today_str}/3?MD=1"
    ]

    for url in ls_urls:
        try:
            res = requests.get(url, headers=ls_headers, timeout=10)
            if res.status_code != 200:
                continue
            stages = res.json().get("Stages") or []
            for st in stages:
                target_label, high_lim, low_lim = classify_world_league(st.get("Cnm"), st.get("Snm"))
                if not target_label:
                    continue
                for ev in st.get("Events") or []:
                    eps = str(ev.get("Eps", "")).upper().strip()
                    if eps not in ["1Q", "2Q", "HT", "3Q", "4Q", "OT"]:
                        continue
                    t1_list = ev.get("T1") or [{}]
                    t2_list = ev.get("T2") or [{}]
                    
                    h_q1 = safe_int(ev.get("Tr1Q1", 0))
                    a_q1 = safe_int(ev.get("Tr2Q1", 0))
                    h_q2 = safe_int(ev.get("Tr1Q2", 0))
                    a_q2 = safe_int(ev.get("Tr2Q2", 0))
                    h_q3 = safe_int(ev.get("Tr1Q3", 0))
                    a_q3 = safe_int(ev.get("Tr2Q3", 0))

                    normalized_games.append({
                        "source": "LiveScore",
                        "id": f"ls_{ev.get('Eid', '')}",
                        "league": target_label,
                        "high_limit": high_lim,
                        "low_limit": low_lim,
                        "period": eps,
                        "home_name": t1_list[0].get("Nm", "Ev"),
                        "away_name": t2_list[0].get("Nm", "Deplasman"),
                        "home_total": safe_int(ev.get("Tr1", 0)),
                        "away_total": safe_int(ev.get("Tr2", 0)),
                        "h_q1": h_q1, "a_q1": a_q1,
                        "h_q3_accum": h_q1 + h_q2 + h_q3,
                        "a_q3_accum": a_q1 + a_q2 + a_q3,
                        "h_q4": safe_int(ev.get("Tr1Q4", 0)),
                        "a_q4": safe_int(ev.get("Tr2Q4", 0)),
                    })
            if normalized_games:
                return normalized_games, "LiveScore"
        except Exception:
            continue

    sf_headers = {
        **BROWSER_HEADERS,
        "Origin": "https://www.sofascore.com",
        "Referer": "https://www.sofascore.com/"
    }
    try:
        res = requests.get("https://api.sofascore.com/api/v1/sport/basketball/events/live", headers=sf_headers, timeout=10)
        if res.status_code == 200:
            for ev in res.json().get("events") or []:
                tourn = ev.get("tournament") or {}
                cat_name = (tourn.get("category") or {}).get("name", "")
                tourn_name = tourn.get("name", "")
                target_label, high_lim, low_lim = classify_world_league(cat_name, tourn_name)
                if not target_label:
                    continue

                st_desc = str((ev.get("status") or {}).get("description", "")).lower()
                eps = "LIVE"
                if "1st" in st_desc:
                    eps = "1Q"
                elif "2nd" in st_desc:
                    eps = "2Q"
                elif "halftime" in st_desc:
                    eps = "HT"
                elif "3rd" in st_desc:
                    eps = "3Q"
                elif "4th" in st_desc:
                    eps = "4Q"
                elif "overtime" in st_desc:
                    eps = "OT"

                h_sc = ev.get("homeScore") or {}
                a_sc = ev.get("awayScore") or {}
                
                h_q1 = safe_int(h_sc.get("period1", 0))
                a_q1 = safe_int(a_sc.get("period1", 0))
                h_q2 = safe_int(h_sc.get("period2", 0))
                a_q2 = safe_int(a_sc.get("period2", 0))
                h_q3 = safe_int(h_sc.get("period3", 0))
                a_q3 = safe_int(a_sc.get("period3", 0))

                normalized_games.append({
                    "source": "Sofascore",
                    "id": f"sf_{ev.get('id', '')}",
                    "league": target_label,
                    "high_limit": high_lim,
                    "low_limit": low_lim,
                    "period": eps,
                    "home_name": (ev.get("homeTeam") or {}).get("shortName") or (ev.get("homeTeam") or {}).get("name", "Ev"),
                    "away_name": (ev.get("awayTeam") or {}).get("shortName") or (ev.get("awayTeam") or {}).get("name", "Deplasman"),
                    "home_total": safe_int(h_sc.get("current", 0)),
                    "away_total": safe_int(a_sc.get("current", 0)),
                    "h_q1": h_q1, "a_q1": a_q1,
                    "h_q3_accum": h_q1 + h_q2 + h_q3,
                    "a_q3_accum": a_q1 + a_q2 + a_q3,
                    "h_q4": safe_int(h_sc.get("period4", 0)),
                    "a_q4": safe_int(a_sc.get("period4", 0)),
                })
            if normalized_games:
                return normalized_games, "Sofascore"
    except Exception:
        pass

    return [], "Aktif Mac Yok"


def check_keyless_world_basketball():
    stake_high = int(KASA_TUTARI * 0.10)  # 2 Birim (200 TL)
    stake_low = int(KASA_TUTARI * 0.05)   # 1 Birim (100 TL)

    games, source_used = fetch_world_basketball_games()

    for g in games:
        game_id = g["id"]
        target_label = g["league"]
        high_limit = g["high_limit"]
        low_limit = g["low_limit"]
        eps = g["period"]

        home_name = g["home_name"]
        away_name = g["away_name"]
        home_total = g["home_total"]
        away_total = g["away_total"]
        total_score = home_total + away_total
        score_diff = abs(home_total - away_total)

        h_q1 = g["h_q1"]
        a_q1 = g["a_q1"]
        q1_total = h_q1 + a_q1
        q1_diff = abs(h_q1 - a_q1)

        if eps == "2Q" and q1_total > 0:
            q2_scored = total_score - q1_total
            if 2 <= q2_scored <= 15:
                if q1_total >= high_limit and q1_diff >= 5:
                    alert_key = f"{game_id}_under"
                    msg = (
                        f"🏀 **BASKETBOL ALARMI (TEMPO DÜŞÜŞÜ ALT)** 🏀\n\n"
                        f"⚔️ **Maç:** {home_name} - {away_name}\n"
                        f"🏆 **Lig:** {target_label}\n"
                        f"⏱️ **Süre:** 2. Çeyrek Başı | Toplam Skor: {total_score}\n"
                        f"📊 **1. Çeyrek Skoru:** {h_q1} - {a_q1} ({q1_total} Sayı)\n\n"
                        f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ALT**\n"
                        f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55 Bandı\n"
                        f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_low} TL** (1 Birim)"
                    )
                    send_telegram_message(alert_key, msg, match_id=game_id)

                elif q1_total <= low_limit:
                    alert_key = f"{game_id}_over"
                    msg = (
                        f"🏀 **BASKETBOL ALARMI (DÜŞÜK BAREM ÜST)** 🏀\n\n"
                        f"⚔️ **Maç:** {home_name} - {away_name}\n"
                        f"🏆 **Lig:** {target_label}\n"
                        f"⏱️ **Süre:** 2. Çeyrek Başı | Toplam Skor: {total_score}\n"
                        f"📊 **1. Çeyrek Skoru:** {h_q1} - {a_q1} ({q1_total} Sayı)\n\n"
                        f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ÜST**\n"
                        f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.55 Bandı\n"
                        f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_low} TL** (1 Birim)"
                    )
                    send_telegram_message(alert_key, msg, match_id=game_id)

                if (a_q1 - h_q1 >= 8) and (home_total - away_total >= -13):
                    alert_key = f"{game_id}_hcp"
                    msg = (
                        f"🏀 **BASKETBOL EV SAHİBİ GERİ DÖNÜŞ** 🏀\n\n"
                        f"⚔️ **Maç:** {home_name} - {away_name}\n"
                        f"🏆 **Lig:** {target_label}\n"
                        f"⏱️ **Süre:** 2. Çeyrek Başı | Skor: {home_total} - {away_total}\n"
                        f"📊 **1. Çeyrek Skoru:** {h_q1} - {a_q1}\n\n"
                        f"💡 **TAVSİYE BAHİS:** {home_name} **+ Handikap**\n"
                        f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.70 Bandı\n"
                        f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_low} TL** (1 Birim)"
                    )
                    send_telegram_message(alert_key, msg, match_id=game_id)

        elif eps == "4Q":
            q4_scored = g["h_q4"] + g["a_q4"]
            q3_accum = g["h_q3_accum"] + g["a_q3_accum"]

            if (18 <= q4_scored <= 52) and (1 <= score_diff <= 5):
                alert_key = f"{game_id}_foul_over"
                msg = (
                    f"🔥 **SNIPER SON DAKİKA (TAKTİK FAUL ÜST)** 🔥\n\n"
                    f"⚔️ **Maç:** {home_name} - {away_name}\n"
                    f"🏆 **Lig:** {target_label}\n"
                    f"⏱️ **Süre:** 4. Çeyrek Son Bölümü | Skor: {home_total} - {away_total}\n\n"
                    f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ÜST**\n"
                    f"🎯 **Bilyoner Target Oranı:** 1.50 - 1.75 Bandı\n"
                    f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_high} TL** (2 Birim)"
                )
                send_telegram_message(alert_key, msg, match_id=game_id)

            elif (4 <= q4_scored <= 20) and (score_diff >= 18) and (q3_accum <= 138):
                alert_key = f"{game_id}_blowout_under"
                msg = (
                    f"❄️ **BASKETBOL RÖLANTİ ALARMI (FARK AÇILDI ALT)** ❄️\n\n"
                    f"⚔️ **Maç:** {home_name} - {away_name}\n"
                    f"🏆 **Lig:** {target_label}\n"
                    f"⏱️ **Süre:** 4. Çeyrek | Skor: {home_total} - {away_total}\n\n"
                    f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ALT**\n"
                    f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.60 Bandı\n"
                    f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_low} TL** (1 Birim)"
                )
                send_telegram_message(alert_key, msg, match_id=game_id)

    return len(games)


def check_live_basketball():
    now_us_east = datetime.now(timezone.utc) - timedelta(hours=5)
    us_dates = [now_us_east.strftime("%Y%m%d")]
    if now_us_east.hour < 5:
        us_dates.append((now_us_east - timedelta(days=1)).strftime("%Y%m%d"))

    stake_high = int(KASA_TUTARI * 0.10)
    stake_low = int(KASA_TUTARI * 0.05)

    basketball_endpoints = [
        ("Avustralya NBL", "https://site.api.espn.com/apis/site/v2/sports/basketball/nbl/scoreboard", 54, 32, 600, 360, 8),
        ("EuroLeague", "https://site.api.espn.com/apis/site/v2/sports/basketball/eur.euroleague/scoreboard", 50, 30, 600, 360, 9),
        ("FIBA", "https://site.api.espn.com/apis/site/v2/sports/basketball/fiba/scoreboard", 50, 30, 600, 360, 9)
    ]
    for d_str in us_dates:
        basketball_endpoints.append(
            ("NBA", f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d_str}", 66, 43, 720, 480, 9)
        )
        basketball_endpoints.append(
            ("NBA G League", f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba-development/scoreboard?dates={d_str}", 66, 43, 720, 480, 9)
        )
        basketball_endpoints.append(
            ("NCAA", f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates={d_str}", 84, 54, 1200, 960, 9)
        )

    seen_live_ids = set()

    for default_league, url, high_limit, low_limit, p2_start_sec, p2_end_sec, hcp_limit in basketball_endpoints:
        try:
            res = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
            if res.status_code != 200:
                continue
            data = res.json()
        except Exception:
            continue

        leagues_list = data.get("leagues") or [{}]
        league_name = leagues_list[0].get("abbreviation", default_league)
        if default_league in ["Avustralya NBL", "NBA G League"]:
            league_name = default_league
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

            home_total = safe_int(home.get("score", 0))
            away_total = safe_int(away.get("score", 0))
            total_score = home_total + away_total
            score_diff = abs(home_total - away_total)
            rem_secs = parse_remaining_seconds(display_clock)

            has_odds, home_fav, away_fav, spread_val, odds_details = get_match_odds_info(comp)

            if period == 2 and (p2_end_sec <= rem_secs <= p2_start_sec):
                home_lines = home.get("linescores", [])
                away_lines = away.get("linescores", [])
                if home_lines and away_lines:
                    h_q1 = safe_int(home_lines[0].get("value", 0))
                    a_q1 = safe_int(away_lines[0].get("value", 0))
                    q1_total = h_q1 + a_q1
                    q1_diff = abs(h_q1 - a_q1)
                    period_label = "1. Yarı" if default_league == "NCAA" else "1. Çeyrek"

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
                            f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_low} TL** (1 Birim)"
                        )
                        send_telegram_message(alert_key, msg, match_id=event_id)

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
                            f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_low} TL** (1 Birim)"
                        )
                        send_telegram_message(alert_key, msg, match_id=event_id)

                    is_confirmed_home_fav = has_odds and home_fav and not away_fav and (spread_val is None or spread_val <= -2.5)
                    if is_confirmed_home_fav and (a_q1 - h_q1 >= hcp_limit) and (home_total - away_total >= -14):
                        alert_key = f"bb_{event_id}_hcp"
                        msg = (
                            f"🏀 **SNIPER: FAVORİ EV SAHİBİ HANDİKAP** 🏀\n\n"
                            f"⚔️ **Maç:** {home_name} - {away_name}\n"
                            f"🏆 **Lig:** {league_name}\n"
                            f"⏱️ **Süre:** 2. Periyot {display_clock} | Skor: {home_total} - {away_total}\n\n"
                            f"💡 **TAVSİYE BAHİS:** {home_name} **+ Handikap**\n"
                            f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.70 Bandı\n"
                            f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_high} TL** (2 Birim)"
                        )
                        send_telegram_message(alert_key, msg, match_id=event_id)

            final_period = 2 if default_league == "NCAA" else 4
            if period == final_period:
                if (40 <= rem_secs <= 220) and (1 <= score_diff <= 5):
                    alert_key = f"bb_{event_id}_foul_over"
                    msg = (
                        f"🔥 **SNIPER SON DAKİKA (TAKTİK FAUL ÜST)** 🔥\n\n"
                        f"⚔️ **Maç:** {home_name} - {away_name}\n"
                        f"🏆 **Lig:** {league_name}\n"
                        f"⏱️ **Süre:** Son Periyot {display_clock} | Skor: {home_total} - {away_total}\n\n"
                        f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ÜST**\n"
                        f"🎯 **Bilyoner Target Oranı:** 1.50 - 1.75 Bandı\n"
                        f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_high} TL** (2 Birim - Yüksek Güven)"
                    )
                    send_telegram_message(alert_key, msg, match_id=event_id)

                elif (300 <= rem_secs <= 510) and (score_diff >= 18):
                    alert_key = f"bb_{event_id}_blowout_under"
                    msg = (
                        f"❄️ **BASKETBOL RÖLANTİ ALARMI (FARK AÇILDI ALT)** ❄️\n\n"
                        f"⚔️ **Maç:** {home_name} - {away_name}\n"
                        f"🏆 **Lig:** {league_name}\n"
                        f"⏱️ **Süre:** Son Periyot {display_clock} | Skor: {home_total} - {away_total}\n\n"
                        f"💡 **TAVSİYE BAHİS:** Canlı Toplam Sayı **ALT**\n"
                        f"🎯 **Bilyoner Target Oranı:** 1.45 - 1.60 Bandı\n"
                        f"💰 **Önerilen Bahis ({KASA_TUTARI} TL Kasa):** **{stake_low} TL** (1 Birim)"
                    )
                    send_telegram_message(alert_key, msg, match_id=event_id)

    cdn_count = check_keyless_world_basketball()
    return len(seen_live_ids) + cdn_count


if __name__ == "__main__":
    print("Canli mac tarama botu baslatildi (Korner ve Basketbol Modu)...")
    live_fb = check_live_football()
    live_bb = check_live_basketball()
    print(f"Tarama tamamlandi. Canli Futbol: {live_fb}, Canli Basketbol: {live_bb}")

    # Her saat başı (sadece ilk 1-2 dakika içinde) yalnızca 1 kez otomatik arka plan durum raporu gönderir
    now_utc = datetime.now(timezone.utc)
    if now_utc.minute < 2:
        status_msg = (
            f"🤖 **Otomatik Arka Plan Raporu**\n"
            f"⚽ Taranan Canlı Futbol: **{live_fb}** maç\n"
            f"🏀 Taranan Canlı Basketbol: **{live_bb}** maç\n"
            f"💼 Aktif Kasa: **{KASA_TUTARI} TL** (1 Birim: {int(KASA_TUTARI * 0.05)} TL)"
        )
        send_telegram_message("hourly_status", status_msg)
