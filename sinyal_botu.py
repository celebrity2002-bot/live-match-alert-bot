#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canlı Sinyal Botu v2.9.5 - İlk Yarı 0-0 Baskı Kurgusu, Gol Olur / Gol Olmaz Ayrımı ve Çizgi Esnekliği
"""
import io
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except Exception:
    Image = ImageDraw = ImageFont = None
    HAS_PIL = False

# ------------------------------------------------------------------
# AYARLAR
# ------------------------------------------------------------------
BASE = Path(__file__).resolve().parent
STATE_PATH = BASE / "state.json"

TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def env_num(name, default, cast=float):
    try:
        return cast(os.getenv(name, "").strip() or default)
    except ValueError:
        return cast(default)


def env_float_or_none(v):
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(str(v).strip())
    except (ValueError, TypeError):
        return None


MODE = (os.getenv("BOT_MODE", "paper") or "paper").strip().lower()   # paper | live
BANKROLL = env_num("BANKROLL_TL", 2000)
STAKE_PCT = env_num("STAKE_PCT", 1.0)
ENABLE_BASKETBALL = os.getenv("ENABLE_BASKETBALL", "1") == "1"
ENABLE_FOOTBALL = os.getenv("ENABLE_FOOTBALL", "1") == "1"
ENABLE_STAT_FILTER = os.getenv("ENABLE_STAT_FILTER", "1") == "1"
REQUIRE_STAT_FOR_00 = os.getenv("REQUIRE_STAT_FOR_00", "1") == "1"
ENABLE_PNG_CARD = os.getenv("ENABLE_PNG_CARD", "1") == "1"
MIN_TARGET_ODDS = env_num("MIN_TARGET_ODDS", 1.65, float)
MIN_TOTAL_XG = env_num("MIN_TOTAL_XG", 0.55, float)
MIN_OPEN_MATCH_XG = env_num("MIN_OPEN_MATCH_XG", 0.85, float)
MIN_OPEN_MATCH_ACTIVITY = env_num("MIN_OPEN_MATCH_ACTIVITY", 10, int)
MAX_GOAL_DIFF_FOR_MOMENTUM = env_num("MAX_GOAL_DIFF_FOR_MOMENTUM", 2, int)
MIN_IY1_00_XG = env_num("MIN_IY1_00_XG", 0.45, float)
MIN_IY1_00_SOT = env_num("MIN_IY1_00_SOT", 2, int)
MIN_IY1_00_ACTIVITY = env_num("MIN_IY1_00_ACTIVITY", 8, int)
MIN_IY2_SOT = env_num("MIN_IY2_SOT", 3, int)
MIN_IY2_ACTIVITY = env_num("MIN_IY2_ACTIVITY", 9, int)
MIN_KG_ACTIVITY = env_num("MIN_KG_ACTIVITY", 7, int)
MIN_KG_TRAILING_SHOTS = env_num("MIN_KG_TRAILING_SHOTS", 3, int)
MIN_KG_TRAILING_SOT = env_num("MIN_KG_TRAILING_SOT", 2, int)

# Düşük isabetli / kırılgan / yüksek varyanslı stratejiler varsayılan pasif
DEFAULT_DISABLED = {
    "FB_IY2_00",
    "FB_TEK_FARK_70",
    "FB_GERIDEN_FARK2",
    "FB_KG_VAR_ACIK_MAC",
    "OZEL_FB_BASKI_SIKISMA",
    "BB_Q4_YAKIN_UST",
    "BB_Q4_FARK_ALT",
    "OZEL_BB_BENCH_COKUS",
    "BB_TEMPO_DUSUSU_ALT",
}
ENV_DISABLED = {x.strip().upper() for x in os.getenv("DISABLE_STRATEGIES", "").split(",") if x.strip()}
DISABLED = DEFAULT_DISABLED | ENV_DISABLED

# Her maçtan (futbol veya basketbol) en fazla 1 sinyal
MAX_LIVE_PER_MATCH = env_num("MAX_LIVE_PER_MATCH", 1, int)
SEND_RESULTS = (os.getenv("SEND_RESULTS", "on") or "on").strip().lower()
HIDE_DISABLED_IN_SUMMARY = os.getenv("HIDE_DISABLED_IN_SUMMARY", "1") == "1"

# Minimum bahis tutarı kuralı (En az 50 TL)
MIN_STAKE_TL = env_num("MIN_STAKE_TL", 50, int)

# Futbol için bülten uyumu yüksek üst lig ve Avrupa kupası anahtar kelimeleri
default_football_keywords = (
    "super lig,süper lig,premier league,la liga,serie a,bundesliga,ligue 1,"
    "champions league,europa league,conference league,eredivisie,liga portugal,"
    "super league greece,pro league"
)
ALLOWED_FOOTBALL_KEYWORDS = {
    x.strip().lower()
    for x in os.getenv("ALLOWED_FOOTBALL_KEYWORDS", default_football_keywords).split(",")
    if x.strip()
}

default_blocked_football_keywords = (
    "ghana,nigeria,kenya,tanzania,uganda,zambia,ethiopia,rwanda,"
    "reserve,reserves,u19,u21,youth"
)
BLOCKED_FOOTBALL_KEYWORDS = {
    x.strip().lower()
    for x in os.getenv("BLOCKED_FOOTBALL_KEYWORDS", default_blocked_football_keywords).split(",")
    if x.strip()
}

# Basketbol için bülten uyumu yüksek ana lig ve kupa anahtar kelimeleri
default_basketball_keywords = (
    "euroleague,eurocup,champions league,nba,bsl,super lig,süper lig,"
    "acb,serie a,bundesliga,pro a,aba,vtb,tbl"
)
ALLOWED_BASKETBALL_KEYWORDS = {
    x.strip().lower()
    for x in os.getenv("ALLOWED_BASKETBALL_KEYWORDS", default_basketball_keywords).split(",")
    if x.strip()
}

# Basketbol eşikleri
BB_Q1_HIGH = env_num("BB_Q1_HIGH", 56, int)
BB_Q1_LOW = env_num("BB_Q1_LOW", 36, int)
BB_Q2_MAX_POINTS = env_num("BB_Q2_MAX_POINTS", 15, int)
BB_Q4_MAX_POINTS = env_num("BB_Q4_MAX_POINTS", 8, int)
BB_HT_HIGH = env_num("BB_HT_HIGH", 95, int)
BB_HT_LOW = env_num("BB_HT_LOW", 70, int)

# Futbol güncel kontrol dakikaları (1.65+ değer pencereleri)
FB_IY1_00_MIN = env_num("FB_IY1_00_MIN", 20, int)
FB_IY1_00_MAX = env_num("FB_IY1_00_MAX", 39, int)
FB_LATE_MIN = env_num("FB_LATE_MIN", 65, int)
FB_LATE_MAX = env_num("FB_LATE_MAX", 80, int)
FB_OPEN_MIN_GOALS = env_num("FB_OPEN_MIN_GOALS", 2, int)
FB_OPEN_MIN_MIN = env_num("FB_OPEN_MIN_MIN", 25, int)
FB_OPEN_MAX_MIN = env_num("FB_OPEN_MAX_MIN", 52, int)
FB_IY2_00_MIN = env_num("FB_IY2_00_MIN", 47, int)
FB_IY2_00_MAX = env_num("FB_IY2_00_MAX", 56, int)
FB_KG_MIN = env_num("FB_KG_MIN", 48, int)
FB_KG_MAX = env_num("FB_KG_MAX", 64, int)
FB_EARLY_HIGH_MIN_START = env_num("FB_EARLY_HIGH_MIN_START", 15, int)
FB_EARLY_HIGH_MIN_END = env_num("FB_EARLY_HIGH_MIN_END", 34, int)

MISSING_RUNS_TO_SETTLE = 3

URLS = {
    "basketball": "https://prod-public-api.livescore.com/v1/api/app/live/basketball/3?MD=1",
    "football": "https://prod-public-api.livescore.com/v1/api/app/live/soccer/1?MD=1",
}
FB_STATS_URL = "https://prod-public-api.livescore.com/v1/api/app/statistics/soccer/{eid}"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
]
FINAL_CODES = {"FT", "AET", "AP", "AOT", "ENDED", "FINISHED", "AFTER OT", "AFTER ET", "AFTER PEN"}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------
# STATE
# ------------------------------------------------------------------
def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            log(f"state.json okunamadı, yeni oluşturuluyor: {exc}")
    return {"signals": {}}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------
# YARDIMCI
# ------------------------------------------------------------------
def num(v):
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return None


def team_name(event, key):
    t = event.get(key)
    if isinstance(t, list) and t:
        t = t[0]
    if isinstance(t, dict):
        return str(t.get("Nm", "?")).strip()
    return "?"


def fetch(sport):
    for attempt in range(3):
        try:
            r = requests.get(
                URLS[sport],
                headers={
                    "User-Agent": random.choice(USER_AGENTS),
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www.livescore.com/",
                },
                timeout=12,
            )
            if r.status_code == 200:
                return r.json()
            log(f"{sport}: HTTP {r.status_code} (deneme {attempt + 1})")
        except Exception as exc:
            log(f"{sport}: istek hatası {exc} (deneme {attempt + 1})")
        time.sleep(2)
    return None


def fetch_fb_stats(eid):
    if not eid:
        return None
    url = FB_STATS_URL.format(eid=eid)
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.livescore.com/",
            },
            timeout=10,
        )
        if r.status_code != 200:
            return None
        payload = r.json()
        stat_list = payload.get("Stat") if isinstance(payload, dict) else None
        if not isinstance(stat_list, list) or len(stat_list) < 2:
            return None

        t1 = stat_list[0] if isinstance(stat_list[0], dict) else {}
        t2 = stat_list[1] if isinstance(stat_list[1], dict) else {}

        xg1 = env_float_or_none(t1.get("Xg"))
        xg2 = env_float_or_none(t2.get("Xg"))
        total_xg = None
        if xg1 is not None or xg2 is not None:
            total_xg = (xg1 or 0.0) + (xg2 or 0.0)

        sot1, sot2 = num(t1.get("Shon")) or 0, num(t2.get("Shon")) or 0
        shof1, shof2 = num(t1.get("Shof")) or 0, num(t2.get("Shof")) or 0
        shots1, shots2 = sot1 + shof1, sot2 + shof2
        cos1, cos2 = num(t1.get("Cos")) or 0, num(t2.get("Cos")) or 0
        ycs1, ycs2 = num(t1.get("Ycs")) or 0, num(t2.get("Ycs")) or 0
        rcs1, rcs2 = num(t1.get("Rcs")) or 0, num(t2.get("Rcs")) or 0
        pss1, pss2 = num(t1.get("Pss")), num(t2.get("Pss"))

        return {
            "xg_total": total_xg,
            "xg1": xg1,
            "xg2": xg2,
            "sot1": sot1,
            "sot2": sot2,
            "shots1": shots1,
            "shots2": shots2,
            "sot_total": sot1 + sot2,
            "shots_total": shots1 + shots2,
            "corners_total": cos1 + cos2,
            "yc_total": ycs1 + ycs2,
            "rc_total": rcs1 + rcs2,
            "pss1": pss1,
            "pss2": pss2,
        }
    except Exception:
        return None


def format_fb_stat_line(st):
    if not st:
        return None
    parts = []
    if st.get("xg_total") is not None:
        parts.append(f"xG {st['xg_total']:.2f}")
    parts.append(f"Isabetli Sut {st['sot_total']}/{st['shots_total']} ({st['sot1']}-{st['sot2']})")
    parts.append(f"Korner {st['corners_total']}")
    if st.get("rc_total", 0) > 0:
        parts.append(f"Kirmizi Kart {st['rc_total']}")
    elif st.get("yc_total", 0) > 0:
        parts.append(f"Sari Kart {st['yc_total']}")
    return " | ".join(parts)


def passes_fb_stat_filter(p, sd, st):
    sid = sd.get("id")
    if sid == "FB_IY1_00_BASKI":
        if not st:
            return False, "GOL OLMAZ / PAS — 0-0 ilk yarı baskı için canlı istatistik verisi yok"
        sot_tot = st.get("sot_total", 0)
        activity = st.get("shots_total", 0) + st.get("corners_total", 0)
        xg_tot = st.get("xg_total")
        if sot_tot < MIN_IY1_00_SOT or activity < MIN_IY1_00_ACTIVITY:
            return False, (
                f"GOL OLMAZ / PAS — İlk yarı baskı yetersiz "
                f"(isabetli şut {sot_tot}/{MIN_IY1_00_SOT}, şut+korner {activity}/{MIN_IY1_00_ACTIVITY})"
            )
        if xg_tot is not None and xg_tot < MIN_IY1_00_XG:
            return False, f"GOL OLMAZ / PAS — İlk yarı xG düşük (xG {xg_tot:.2f}/{MIN_IY1_00_XG:.2f})"
        return True, None

    if sid in ("FB_ACIK_MAC_DEVAM_GOL", "FB_COK_GOLLU_ERKEN"):
        if p.get("diff", 0) > MAX_GOAL_DIFF_FOR_MOMENTUM:
            return False, (
                f"Skor farkı rölanti filtresi (fark {p.get('diff', 0)} > {MAX_GOAL_DIFF_FOR_MOMENTUM})"
            )
        if ENABLE_STAT_FILTER and st:
            sot_tot = st.get("sot_total", 0)
            activity = st.get("shots_total", 0) + st.get("corners_total", 0)
            xg_tot = st.get("xg_total")
            min_act = MIN_OPEN_MATCH_ACTIVITY if sid == "FB_ACIK_MAC_DEVAM_GOL" else max(7, MIN_OPEN_MATCH_ACTIVITY - 2)
            min_sot = 3 if sid == "FB_ACIK_MAC_DEVAM_GOL" else 2
            if sot_tot < min_sot or activity < min_act:
                return False, (
                    f"İvme üretim filtresi (isabetli şut {sot_tot}/{min_sot}, "
                    f"şut+korner {activity}/{min_act})"
                )
            if xg_tot is not None and xg_tot < MIN_OPEN_MATCH_XG:
                return False, f"İvme xG filtresi (xG {xg_tot:.2f}/{MIN_OPEN_MATCH_XG:.2f})"
        return True, None

    if sid == "FB_KG_VAR_ACIK_MAC":
        if not st:
            return False, "KG Var için canlı istatistik verisi bulunamadı"
        sot1, sot2 = st.get("sot1", 0), st.get("sot2", 0)
        shots1, shots2 = st.get("shots1", 0), st.get("shots2", 0)
        activity = st.get("shots_total", 0) + st.get("corners_total", 0)
        if sot1 < 1 or sot2 < 1 or activity < MIN_KG_ACTIVITY:
            return False, (
                f"KG Var iki yönlü üretim filtresi (isabetli şut {sot1}-{sot2}, "
                f"şut+korner {activity}/{MIN_KG_ACTIVITY})"
            )
        if p.get("home", 0) > p.get("away", 0):
            trailing_shots, trailing_sot = shots2, sot2
        elif p.get("away", 0) > p.get("home", 0):
            trailing_shots, trailing_sot = shots1, sot1
        else:
            trailing_shots, trailing_sot = min(shots1, shots2), min(sot1, sot2)
        if trailing_sot < MIN_KG_TRAILING_SOT or trailing_shots < MIN_KG_TRAILING_SHOTS:
            return False, (
                f"KG Var geride kalan takım şut dengesi (şut {trailing_shots}/{MIN_KG_TRAILING_SHOTS}, "
                f"isabetli şut {trailing_sot}/{MIN_KG_TRAILING_SOT})"
            )
        return True, None

    if p.get("total") == 0 and REQUIRE_STAT_FOR_00 and not st:
        return False, "GOL OLMAZ / PAS — 0-0 maç için canlı istatistik verisi bulunamadı"

    if not ENABLE_STAT_FILTER or not st:
        return True, None
    xg_tot = st.get("xg_total")
    sot_tot = st.get("sot_total", 0)
    activity = st.get("shots_total", 0) + st.get("corners_total", 0)
    if xg_tot is not None and xg_tot < MIN_TOTAL_XG and activity <= 7:
        return False, f"GOL OLMAZ / PAS — Düşük tempo/xG filtresi (xG {xg_tot:.2f}, şut+korner {activity})"
    if sid == "FB_IY2_00" and p.get("total") == 0:
        if sot_tot < MIN_IY2_SOT or activity < MIN_IY2_ACTIVITY:
            return False, (
                f"0-0 düşük üretim filtresi (isabetli şut {sot_tot}/{MIN_IY2_SOT}, "
                f"şut+korner {activity}/{MIN_IY2_ACTIVITY})"
            )
    return True, None


def fb_goal_line_hint(p, res):
    if res.get("market_hint"):
        return res["market_hint"]
    direction = res.get("direction", "over")
    if direction == "under":
        return f"Hedef: ALT ({MIN_TARGET_ODDS:.2f}+ oran bandi) | Skor: {p['total']}"
    tot = p.get("total", 0)
    if tot == 0:
        return "BASKI: GOL OLUR | Sitedeki acik Ust / Gol cizgisine bak"
    if tot == 1:
        return "Hedef: 1.5 Ust / 2.5 Ust (1.65+ bandi) | Skor: 1 gol"
    if tot == 2:
        return f"Hedef: 3.5 Ust / 4.5 Ust (2.5 Ust kapali olabilir) | Skor: {p['home']}-{p['away']}"
    return f"Hedef: {tot + 1.5:.1f} Ust ({tot + 0.5:.1f} kapaliysa) | Skor: {p['home']}-{p['away']}"


def iter_events(data, sport="football"):
    keywords = ALLOWED_BASKETBALL_KEYWORDS if sport == "basketball" else ALLOWED_FOOTBALL_KEYWORDS
    for stage in (data or {}).get("Stages", []) or []:
        league = " ".join(
            x for x in (str(stage.get("Cnm", "")).strip(), str(stage.get("Snm", "")).strip()) if x
        )
        l_lower = league.lower()
        if sport == "football" and BLOCKED_FOOTBALL_KEYWORDS:
            if any(bkw in l_lower for bkw in BLOCKED_FOOTBALL_KEYWORDS):
                continue
        if keywords:
            if not any(kw in l_lower for kw in keywords):
                continue
        for ev in stage.get("Events", []) or []:
            if isinstance(ev, dict) and ev.get("Eid") is not None:
                yield league, ev


def send_telegram(text):
    if not TOKEN or not CHAT_ID:
        log("Telegram bilgileri yok, mesaj gönderilmedi:\n" + text)
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    for attempt in range(3):
        try:
            r = requests.post(url, data={"chat_id": CHAT_ID, "text": text[:4000]}, timeout=12)
            if r.status_code == 200:
                return True
            log(f"Telegram HTTP {r.status_code}: {r.text[:200]}")
        except Exception as exc:
            log(f"Telegram hatası: {exc}")
        time.sleep(2)
    return False


def send_telegram_photo(png_bytes, caption=""):
    if not TOKEN or not CHAT_ID or not png_bytes:
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    for attempt in range(2):
        try:
            payload = {"chat_id": CHAT_ID}
            if caption:
                payload["caption"] = caption[:1024]
            r = requests.post(
                url,
                data=payload,
                files={"photo": ("signal_card.png", io.BytesIO(png_bytes), "image/png")},
                timeout=15,
            )
            if r.status_code == 200:
                return True
            log(f"Telegram sendPhoto HTTP {r.status_code}: {r.text[:200]}")
        except Exception as exc:
            log(f"Telegram sendPhoto hatası: {exc}")
        time.sleep(2)
    return False


# ------------------------------------------------------------------
# DİNAMİK NEON PNG SİNYAL KARTI
# ------------------------------------------------------------------
def _load_font(size, bold=False):
    if not HAS_PIL:
        return None
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _fit_text(draw, text, max_width, start_size, bold=True, min_size=18):
    size = start_size
    while size >= min_size:
        font = _load_font(size, bold=bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return text, font
        size -= 2
    font = _load_font(min_size, bold=bold)
    trimmed = text
    while len(trimmed) > 3:
        trimmed = trimmed[:-4] + "..."
        bbox = draw.textbbox((0, 0), trimmed, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            break
    return trimmed, font


def _draw_rounded_box(draw, xy, radius, fill, outline=None, width=3):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def build_signal_card_png(p, sd, res, stat_line=None):
    if not (HAS_PIL and ENABLE_PNG_CARD):
        return None
    try:
        w, h = 900, 1200
        is_under = res.get("direction") == "under"
        accent = (255, 68, 78) if is_under else (46, 255, 118)
        accent_dark = (72, 16, 22) if is_under else (14, 62, 28)
        pill_bg = (110, 22, 30) if is_under else (22, 95, 42)
        bg_color = (7, 11, 10)
        panel_bg = (14, 21, 18)
        row_bg = (22, 30, 27)
        text_main = (244, 248, 246)
        text_muted = (166, 180, 173)

        img = Image.new("RGB", (w, h), bg_color)
        draw = ImageDraw.Draw(img)

        _draw_rounded_box(draw, (24, 24, w - 24, h - 24), 44, panel_bg, outline=accent, width=6)
        _draw_rounded_box(draw, (42, 42, w - 42, h - 42), 34, None, outline=accent_dark, width=2)

        f_top = _load_font(30, bold=True)
        f_badge = _load_font(22, bold=True)
        draw.text((74, 68), "CANLI MAC TAKIP BOTU", fill=text_main, font=f_top)
        _draw_rounded_box(draw, (w - 220, 62, w - 74, 108), 18, pill_bg, outline=accent, width=2)
        b_txt = "GOL OLUR" if sd.get("id") == "FB_IY1_00_BASKI" else "CANLI"
        bb = draw.textbbox((0, 0), b_txt, font=f_badge)
        draw.text(
            (w - 147 - (bb[2] - bb[0]) // 2, 85 - (bb[3] - bb[1]) // 2),
            b_txt,
            fill=text_main,
            font=f_badge,
        )

        arrow_x = 115
        arrow_y = 195
        if is_under:
            draw.polygon(
                [
                    (arrow_x - 36, arrow_y - 34),
                    (arrow_x + 36, arrow_y - 34),
                    (arrow_x + 36, arrow_y + 6),
                    (arrow_x + 56, arrow_y + 6),
                    (arrow_x, arrow_y + 46),
                    (arrow_x - 56, arrow_y + 6),
                    (arrow_x - 36, arrow_y + 6),
                ],
                fill=accent,
            )
            main_title = "ALT SINYALI"
        else:
            draw.polygon(
                [
                    (arrow_x, arrow_y - 46),
                    (arrow_x + 56, arrow_y - 6),
                    (arrow_x + 36, arrow_y - 6),
                    (arrow_x + 36, arrow_y + 34),
                    (arrow_x - 36, arrow_y + 34),
                    (arrow_x - 36, arrow_y - 6),
                    (arrow_x - 56, arrow_y - 6),
                ],
                fill=accent,
            )
            if sd.get("id") == "FB_IY1_00_BASKI":
                main_title = "0-0 BASKI: GOL OLUR"
            elif sd.get("id") == "FB_KG_VAR_ACIK_MAC":
                main_title = "KG VAR SINYALI"
            else:
                main_title = "GOL / UST SINYALI" if p["sport"] == "football" else "UST SINYALI"

        t_main, f_main = _fit_text(draw, main_title, w - 260, 56, bold=True, min_size=36)
        draw.text((195, 162), t_main, fill=accent, font=f_main)

        match_txt, f_match = _fit_text(draw, p["match"], w - 140, 48, bold=True, min_size=30)
        mb = draw.textbbox((0, 0), match_txt, font=f_match)
        draw.text(((w - (mb[2] - mb[0])) // 2, 275), match_txt, fill=text_main, font=f_match)

        first_line = res["detail"].split("\n")[0]
        sub_txt, f_sub = _fit_text(draw, first_line, w - 140, 32, bold=True, min_size=22)
        sb = draw.textbbox((0, 0), sub_txt, font=f_sub)
        draw.text(((w - (sb[2] - sb[0])) // 2, 338), sub_txt, fill=text_muted, font=f_sub)

        if p.get("league"):
            lg_txt, f_lg = _fit_text(draw, p["league"], w - 160, 24, bold=False, min_size=18)
            lb = draw.textbbox((0, 0), lg_txt, font=f_lg)
            draw.text(((w - (lb[2] - lb[0])) // 2, 382), lg_txt, fill=text_muted, font=f_lg)

        metric_rows = []
        if p["sport"] == "football":
            metric_rows.append(fb_goal_line_hint(p, res))
            if stat_line:
                for chunk in [x.strip() for x in stat_line.split("|") if x.strip()]:
                    if len(metric_rows) < 3:
                        metric_rows.append(chunk)
            if len(metric_rows) < 3:
                metric_rows.append(f"Mevcut Skor: {p['home']}-{p['away']} ({p['total']} gol)")
            if len(metric_rows) < 3:
                metric_rows.append(f"Pencere: {sd['label']}")
        else:
            q_str = " / ".join(str(x) for x in (p.get("q") or []) if x is not None)
            metric_rows.append(f"Toplam Sayi: {p['total']}  (Fark: {p['diff']})")
            metric_rows.append(f"Ceyrekler: {q_str if q_str else 'Canli'}")
            metric_rows.append(f"Strateji: {sd['label']}")

        y_cursor = 435
        for m_text in metric_rows[:3]:
            _draw_rounded_box(draw, (74, y_cursor, w - 74, y_cursor + 86), 22, row_bg, outline=(52, 68, 62), width=2)
            m_fit, f_m = _fit_text(draw, m_text, w - 190, 30, bold=True, min_size=20)
            draw.text((104, y_cursor + 26), m_fit, fill=text_main, font=f_m)
            y_cursor += 104

        band = sd["band"]
        play_txt, f_play = _fit_text(draw, f"OYNA: {sd['pick']}", w - 160, 36, bold=True, min_size=24)
        _draw_rounded_box(draw, (74, y_cursor + 8, w - 74, y_cursor + 88), 40, pill_bg, outline=accent, width=3)
        pb = draw.textbbox((0, 0), play_txt, font=f_play)
        draw.text(((w - (pb[2] - pb[0])) // 2, y_cursor + 28), play_txt, fill=text_main, font=f_play)

        band_str = f"Oran Bandi: {band[0]:.2f} - {band[1]:.2f}   |   Tutar: {stake_tl()} TL"
        band_txt, f_band = _fit_text(draw, band_str, w - 160, 32, bold=True, min_size=22)
        _draw_rounded_box(draw, (74, y_cursor + 104, w - 74, y_cursor + 184), 40, (20, 46, 30), outline=accent, width=3)
        bb2 = draw.textbbox((0, 0), band_txt, font=f_band)
        draw.text(((w - (bb2[2] - bb2[0])) // 2, y_cursor + 124), band_txt, fill=text_main, font=f_band)

        warn_txt, f_warn = _fit_text(
            draw,
            f"Acik cizgiye bak; {MIN_TARGET_ODDS:.2f} altindaysa veya uymuyorsa PAS",
            w - 130,
            24,
            bold=True,
            min_size=18,
        )
        wb = draw.textbbox((0, 0), warn_txt, font=f_warn)
        draw.text(((w - (wb[2] - wb[0])) // 2, h - 102), warn_txt, fill=accent, font=f_warn)

        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception as exc:
        log(f"PNG kart üretilemedi, düz metne düşülüyor: {exc}")
        return None


def breakeven(band):
    return 100.0 / ((band[0] + band[1]) / 2)


def stake_tl():
    hesaplanan = round(BANKROLL * STAKE_PCT / 100.0)
    return max(MIN_STAKE_TL, hesaplanan)


def decay_risk_note(p):
    if p["sport"] == "football":
        if p.get("minute") is not None and p["minute"] >= 58:
            return f"Yüksek — oran {MIN_TARGET_ODDS:.2f} altındaysa veya kapalıysa PAS"
        return f"Orta — sitede açık çizgiyi kontrol et, {MIN_TARGET_ODDS:.2f}+ ise değerlendir"
    return f"Orta — çizgi/oran {MIN_TARGET_ODDS:.2f} bandındaysa değerlendir, düşükse PAS"


def form_note(state, sid, band, sport):
    same = [r for r in state.get("signals", {}).values()
            if r.get("strategy") == sid and r.get("status") in ("won", "lost")]
    done = len(same)
    be = breakeven(band)
    if done == 0:
        hist = "İlk sinyal | Az örneklem"
    else:
        won = sum(1 for r in same if r.get("status") == "won")
        rate = 100.0 * won / done
        sample_tag = "Az örneklem" if done < 20 else f"{done} sinyal"
        status_tag = "Karne zayıf" if (done >= 4 and rate < be) else "Karne izleniyor"
        hist = f"Geçmiş {won}/{done} (%{rate:.0f}) | {sample_tag} | {status_tag}"

    band_txt = f"Değer bandı {band[0]:.2f}-{band[1]:.2f}"
    action = f"{band_txt} (çizgi/oran sende)" if sport == "basketball" else f"{band_txt} (sitedeki açık çizgiyi kontrol et)"
    return f"{hist} — {action}"


# ------------------------------------------------------------------
# STRATEJİ KAYIT DEFTERİ
# ------------------------------------------------------------------
STRATS = {}
STRAT_ORDER = []


def strat(sid, sport, label, title, pick, band, is_special=False):
    def deco(fn):
        STRATS[sid] = dict(id=sid, sport=sport, label=label, title=title,
                           pick=pick, band=band, fn=fn, is_special=is_special)
        STRAT_ORDER.append(sid)
        return fn
    return deco


# ------------------------------------------------------------------
# FUTBOL
# ------------------------------------------------------------------
def parse_fb_minute(eps):
    s = str(eps or "").strip().upper().replace("'", "").replace("’", "")
    m = re.match(r"^(\d{1,3})(?:\+(\d{1,2}))?$", s)
    if not m:
        return None
    return int(m.group(1)) + (int(m.group(2)) if m.group(2) else 0)


def parse_football(league, ev):
    h, a = num(ev.get("Tr1")), num(ev.get("Tr2"))
    if h is None or a is None:
        return None
    eps = str(ev.get("Eps", "")).upper().strip()
    eid = str(ev.get("Eid"))
    return {
        "sport": "football",
        "eid": eid,
        "match_id": f"fb_{eid}",
        "match": f"{team_name(ev, 'T1')} - {team_name(ev, 'T2')}",
        "league": league,
        "eps": eps,
        "minute": parse_fb_minute(eps),
        "ht": eps == "HT",
        "home": h,
        "away": a,
        "total": h + a,
        "diff": abs(h - a),
        "final": eps in FINAL_CODES,
    }


def fb_res(p, detail, market_hint=None):
    return {
        "detail": detail,
        "direction": "over",
        "base": p["total"],
        "n": 1,
        "ref": 0.0,
        "market_hint": market_hint,
    }


def fb_in(p, lo, hi):
    return p["minute"] is not None and lo <= p["minute"] <= hi


def fb_line(p):
    t = "Devre Arası" if p["ht"] else f"Dakika: {p['minute']}'"
    return f"{t} | Skor: {p['home']}-{p['away']}"


@strat("FB_IY1_00_BASKI", "football",
       f"İlk Yarı 0-0 Baskı ({FB_IY1_00_MIN}-{FB_IY1_00_MAX}', GOL OLUR)",
       "0-0 BASKI ALARMI — GOL OLUR", "Sitedeki Açık Üst / Gol Çizgisi", (1.65, 2.15))
def fb_iy1_00_baski(p):
    if fb_in(p, FB_IY1_00_MIN, FB_IY1_00_MAX) and p["total"] == 0:
        return fb_res(
            p,
            f"{fb_line(p)}\nKarar: GOL OLUR (baskı barajı aşıldı) — sitede açık olan çizgiyi kontrol et",
            market_hint="Karar: GOL OLUR | Sitedeki acik gol/ust cizgisine bak",
        )


@strat("FB_ACIK_MAC_DEVAM_GOL", "football",
       f"Açık Maç İvmesi ({FB_OPEN_MIN_MIN}-{FB_OPEN_MAX_MIN}', {FB_OPEN_MIN_GOALS}+ gol)",
       "FUTBOL DEĞER ALARMI (AÇIK MAÇ İVMESİ)", "Ek Gol / Canlı Üst", (1.65, 2.15))
def fb_acik_mac_devam_gol(p):
    if (
        fb_in(p, FB_OPEN_MIN_MIN, FB_OPEN_MAX_MIN)
        and p["total"] >= FB_OPEN_MIN_GOALS
        and p["diff"] <= MAX_GOAL_DIFF_FOR_MOMENTUM
    ):
        return fb_res(
            p,
            f"{fb_line(p)}\nSkor açık, fark dengeli ve üretim sürüyor — açık üst çizgisini kontrol et",
            market_hint=f"Hedef: {p['total'] + 1.5:.1f} Ust ({p['total'] + 0.5:.1f} kapaliysa) | Skor: {p['home']}-{p['away']}",
        )


@strat("FB_IY2_00", "football", f"0-0 değer penceresi ({FB_IY2_00_MIN}-{FB_IY2_00_MAX}')",
       "FUTBOL DEĞER ALARMI (0-0, 1.65+ HEDEF)", "1.5 Üst / İkinci Yarı Gol", (1.65, 2.15))
def fb_iy2_00(p):
    if fb_in(p, FB_IY2_00_MIN, FB_IY2_00_MAX) and p["total"] == 0:
        return fb_res(p, f"{fb_line(p)}\nİkinci yarı değer penceresi — 1.09 0.5 Üst yerine 1.65+ değer marketi kontrol et")


@strat("FB_KG_VAR_ACIK_MAC", "football", f"İki Yönlü Açık Maç KG Var ({FB_KG_MIN}-{FB_KG_MAX}')",
       "FUTBOL DEĞER ALARMI (KG VAR 1.65+)", "KG Var (Karşılıklı Gol)", (1.65, 2.15))
def fb_kg_var_acik_mac(p):
    if fb_in(p, FB_KG_MIN, FB_KG_MAX) and p["total"] == 1:
        return fb_res(
            p,
            f"{fb_line(p)}\nTek gollü açık maç penceresi — iki yönlü şut ve hücum dengesi onaylı",
            market_hint=f"Hedef: KG Var (1.65+ bandi) | Skor: {p['home']}-{p['away']}",
        )


@strat("FB_COK_GOLLU_ERKEN", "football", f"Yüksek Tempolu Erken Maç ({FB_EARLY_HIGH_MIN_START}-{FB_EARLY_HIGH_MIN_END}', 3+ gol)",
       "FUTBOL DEĞER ALARMI (TEMPO / EK GOL)", "Sıradaki Gol / Canlı Üst", (1.65, 2.10))
def fb_cok_gollu(p):
    if (
        fb_in(p, FB_EARLY_HIGH_MIN_START, FB_EARLY_HIGH_MIN_END)
        and p["total"] >= 3
        and p["diff"] <= MAX_GOAL_DIFF_FOR_MOMENTUM
    ):
        return fb_res(p, f"{fb_line(p)}\nYüksek tempolu ve kopmamış erken maç — açık üst çizgisini kontrol et")


@strat("FB_GERIDEN_FARK2", "football", "2 gol fark baskısı, 55-80'",
       "FUTBOL DEĞER ALARMI (2 FARK BASKI)", "Sıradaki Gol / Canlı Üst", (1.65, 2.15))
def fb_fark2(p):
    if fb_in(p, 55, 80) and p["diff"] == 2:
        return fb_res(p, f"{fb_line(p)}\n2 gol fark baskısı — reaksiyon ve açık oyun potansiyeli")


@strat("FB_TEK_FARK_70", "football", f"Tek farkla önde, {FB_LATE_MIN}-{FB_LATE_MAX}'",
       "FUTBOL DEĞER ALARMI (TEK FARK)", "Ek Gol Olur / Canlı Üst", (1.65, 2.05))
def fb_tek_fark(p):
    if fb_in(p, FB_LATE_MIN, FB_LATE_MAX) and p["diff"] == 1:
        return fb_res(p, f"{fb_line(p)}\nTek fark üstünlüğü — 1.65+ bandındaki gol marketini kontrol et")


@strat("OZEL_FB_BASKI_SIKISMA", "football", "Görünmeyen Baskı ve Sıkışma (Değer Sinyali)",
       "🔔 DEĞER SİNYALİ (1.65+ Hedef)", "Sıradaki Gol Olur / Canlı Üst", (1.70, 2.20), is_special=True)
def ozel_fb_baski(p):
    if fb_in(p, 65, 78) and p["total"] <= 1:
        return {
            "detail": f"Dakika: {p['minute']}' | Skor: {p['home']}-{p['away']}\n"
                      f"Analiz: Düşük skor beklentisiyle şişen/dengelenen oranlarda baskı ve kırılma potansiyeli.",
            "direction": "over", "base": p["total"], "n": 1, "ref": 0.0
        }
    return None


# ------------------------------------------------------------------
# BASKETBOL
# ------------------------------------------------------------------
def parse_basketball(league, ev):
    eps = str(ev.get("Eps", "")).upper().strip()
    h, a = num(ev.get("Tr1")), num(ev.get("Tr2"))
    if h is None or a is None:
        return None
    m = re.match(r"^(?:Q(\d)|(\d)Q)$", eps)
    period = int(m.group(1) or m.group(2)) if m else (5 if eps == "OT" else None)
    qs = []
    for i in range(1, 5):
        x, y = num(ev.get(f"Tr1Q{i}")), num(ev.get(f"Tr2Q{i}"))
        qs.append(x + y if x is not None and y is not None else None)
    return {
        "sport": "basketball",
        "eid": str(ev.get("Eid")),
        "match_id": f"bb_{ev.get('Eid')}",
        "match": f"{team_name(ev, 'T1')} - {team_name(ev, 'T2')}",
        "league": league,
        "eps": eps,
        "period": period,
        "ht": eps == "HT",
        "home": h,
        "away": a,
        "total": h + a,
        "diff": abs(h - a),
        "q": qs,
        "final": eps in FINAL_CODES,
    }


def _q4_info(p):
    if p["period"] != 4 or any(x is None for x in p["q"][:3]):
        return None
    first3 = sum(p["q"][:3])
    q4_pts = p["total"] - first3
    if 0 <= q4_pts <= BB_Q4_MAX_POINTS:
        return first3, q4_pts
    return None


@strat("OZEL_BB_BENCH_COKUS", "basketball", "Bench Çöküşü / Tempo Kırılması (Özel Sinyal)",
       "🔔 ÖZEL SİNYAL (1.70+ Hedef)", "Canlı Toplam Sayı ALT", (1.70, 2.10), is_special=True)
def ozel_bb_bench(p):
    info = _q4_info(p)
    if info and 140 < p["total"] <= 165 and p["diff"] >= 14:
        first3, _ = info
        return {
            "detail": f"Süre: 4. Çeyrek Başı | Skor: {p['home']}-{p['away']}\n"
                      f"Analiz: Fark {p['diff']} sayıya açıldı ve tempo düşük/orta bantta; olası rotasyon/tempo düşüşü izleniyor.",
            "direction": "under", "base": first3, "n": 1, "ref": first3 / 3.0
        }
    return None


@strat("BB_TEMPO_DUSUSU_ALT", "basketball", "Tempo düşüşü ALT (Q1 yüksek)",
       "BASKETBOL DEĞER ALARMI (TEMPO DÜŞÜŞÜ ALT)", "Canlı Toplam Sayı ALT", (1.65, 1.95))
def bb_tempo_dususu(p):
    q1 = p["q"][0]
    if p["period"] == 2 and q1 is not None and q1 >= BB_Q1_HIGH \
            and 0 <= p["total"] - q1 <= BB_Q2_MAX_POINTS:
        return {"direction": "under", "base": q1, "n": 3, "ref": float(q1),
                "detail": f"Süre: 2. Çeyrek Başı | Toplam Skor: {p['total']}\n1. Çeyrek Toplamı: {q1} sayı"}


@strat("BB_HT_DUSUK_UST", "basketball", "Devre arası düşük skor ÜST",
       "BASKETBOL DEĞER ALARMI (DEVRE ARASI ÜST)", "Canlı Toplam Sayı ÜST", (1.65, 1.95))
def bb_ht_dusuk(p):
    if p["ht"] and 0 < p["total"] <= BB_HT_LOW:
        return {"direction": "over", "base": p["total"], "n": 2, "ref": p["total"] / 2.0,
                "detail": f"Devre Arası | İlk Yarı Toplamı: {p['total']} sayı ({p['home']}-{p['away']})"}


@strat("BB_Q1_DUSUK_UST", "basketball", "Tempo yükselişi ÜST (Q1 düşük)",
       "BASKETBOL DEĞER ALARMI (TEMPO YÜKSELİŞİ ÜST)", "Canlı Toplam Sayı ÜST", (1.65, 2.00))
def bb_q1_dusuk(p):
    q1 = p["q"][0]
    if p["period"] == 2 and q1 is not None and q1 <= BB_Q1_LOW \
            and 0 <= p["total"] - q1 <= BB_Q2_MAX_POINTS:
        return {"direction": "over", "base": q1, "n": 3, "ref": float(q1),
                "detail": f"Süre: 2. Çeyrek Başı | Toplam Skor: {p['total']}\n1. Çeyrek Toplamı: {q1} sayı"}


@strat("BB_Q4_FARK_ALT", "basketball", "4. çeyrek başı büyük fark ALT",
       "BASKETBOL DEĞER ALARMI (4. ÇEYREK FARK ALT)", "Canlı Toplam Sayı ALT", (1.65, 2.00))
def bb_q4_fark(p):
    info = _q4_info(p)
    if info and p["diff"] >= 15:
        first3, _ = info
        return {"direction": "under", "base": first3, "n": 1, "ref": first3 / 3.0,
                "detail": f"Süre: 4. Çeyrek Başı | Skor: {p['home']}-{p['away']} (fark {p['diff']})\nİlk 3 çeyrek ortalaması: {first3 / 3:.1f} sayı"}


@strat("BB_Q4_YAKIN_UST", "basketball", "4. çeyrek başı yakın skor ÜST",
       "BASKETBOL DEĞER ALARMI (4. ÇEYREK YAKIN ÜST)", "Canlı Toplam Sayı ÜST", (1.65, 2.05))
def bb_q4_yakin(p):
    info = _q4_info(p)
    if info and p["diff"] <= 3:
        first3, _ = info
        return {"direction": "over", "base": first3, "n": 1, "ref": first3 / 3.0,
                "detail": f"Süre: 4. Çeyrek Başı | Skor: {p['home']}-{p['away']} (fark {p['diff']})\nİlk 3 çeyrek ortalaması: {first3 / 3:.1f} sayı"}


# ------------------------------------------------------------------
# SİNYAL OLUŞTURMA / SONUÇLANDIRMA
# ------------------------------------------------------------------
def build_message(p, sd, res, state=None, stat_line=None):
    band = sd["band"]
    line = "━━━━━━━━━━━━━━"
    icon = "⚽" if p["sport"] == "football" else "🏀"
    detail = res["detail"].split("\n")
    note = form_note(state or {"signals": {}}, sd["id"], band, p["sport"])
    risk = decay_risk_note(p)

    if sd.get("is_special"):
        lines = [sd["title"], line, f"{icon} {p['match']}"]
        if p.get("league"):
            lines.append(f"🏆 {p['league']}")
        lines.append(f"🏷 {sd['label']}")
        lines.append(f"📊 {detail[0]}")
        if len(detail) > 1:
            lines.append(f"📉 {detail[1]}")
        if p["sport"] == "football":
            lines.append(f"🎯 Çizgi Notu: {fb_goal_line_hint(p, res)}")
        if stat_line:
            lines.append(f"📈 İstatistik: {stat_line}")
        lines += [line,
                  f"🎯 OYNA: {sd['pick']}",
                  f"📈 Değer oran bandı: {band[0]:.2f} - {band[1]:.2f}",
                  f"⚡ Karar / Risk: {risk}",
                  f"💰 Tutar: {stake_tl()} TL (Min: {MIN_STAKE_TL} TL)",
                  f"🎲 Başa baş isabet: %{breakeven(band):.0f}",
                  f"📌 Form & Not: {note}",
                  "",
                  f"🛑 Sitedeki çizgi uymuyorsa veya oran {MIN_TARGET_ODDS:.2f} altındaysa PAS"]
    else:
        lines = [f"🚨 {sd['title']}", line, f"{icon} {p['match']}"]
        if p.get("league"):
            lines.append(f"🏆 {p['league']}")
        lines.append(f"⏱ {detail[0]}")
        lines += [f"📊 {d}" for d in detail[1:]]
        if p["sport"] == "football":
            lines.append(f"🎯 Çizgi Notu: {fb_goal_line_hint(p, res)}")
        if stat_line:
            lines.append(f"📈 İstatistik: {stat_line}")
        lines += [line,
                  f"🎯 OYNA: {sd['pick']}",
                  f"📈 Değer oran bandı: {band[0]:.2f} - {band[1]:.2f}",
                  f"⚡ Karar / Risk: {risk}",
                  f"💰 Tutar: {stake_tl()} TL (Min: {MIN_STAKE_TL} TL)",
                  f"🎲 Başa baş isabet: %{breakeven(band):.0f}",
                  f"📌 Form & Not: {note}",
                  "",
                  f"🛑 Sitedeki çizgi uymuyorsa, oran {MIN_TARGET_ODDS:.2f} altındaysa veya bant dışındaysa PAS"]
    return "\n".join(lines)


def dispatch_signal_telegram(p, sd, res, state=None, stat_line=None):
    msg_text = build_message(p, sd, res, state, stat_line=stat_line)
    card_bytes = build_signal_card_png(p, sd, res, stat_line=stat_line)
    if card_bytes:
        if send_telegram_photo(card_bytes, caption=""):
            return True
    return send_telegram(msg_text)


def match_already_has_signal(state, match_id):
    return any(r.get("match_id") == match_id for r in state.get("signals", {}).values())


def register_signal(state, p, sd, res, stat_line=None):
    if match_already_has_signal(state, p["match_id"]):
        return False

    key = f"{p['match_id']}|{sd['id']}"
    if key in state["signals"]:
        return False

    rec = {
        "key": key, "sport": p["sport"], "match_id": p["match_id"], "match": p["match"],
        "league": p["league"], "strategy": sd["id"], "pick": sd["pick"], "band": list(sd["band"]),
        "created": datetime.now(timezone.utc).isoformat(),
        "status": "pending", "missing_runs": 0, "last_total": p["total"], "sent": False,
        "result_sent": False,
        "direction": res["direction"], "base": res["base"], "n": res["n"], "ref": res["ref"],
        "signal_score": f"{p['home']}-{p['away']}", "last_score": f"{p['home']}-{p['away']}",
        "stats_summary": stat_line or "",
    }
    state["signals"][key] = rec
    if MODE == "live":
        sent_for_match = sum(1 for r in state["signals"].values()
                             if r["match_id"] == p["match_id"] and r.get("sent"))
        if sent_for_match < MAX_LIVE_PER_MATCH:
            rec["sent"] = dispatch_signal_telegram(p, sd, res, state, stat_line=stat_line)
        else:
            log(f"Bu maç için mesaj sınırına ulaşıldı, sadece kaydedildi: {p['match']} / {sd['id']}")
    else:
        log(f"[PAPER] Kaydedildi: {p['match']} / {sd['id']}")
    return True


def notify_result(state, rec):
    if SEND_RESULTS == "off":
        rec["result_sent"] = True
        return True
    if rec.get("result_sent"):
        return True
    if MODE == "live" and not rec.get("sent"):
        rec["result_sent"] = True
        return True
    rec["result_sent"] = True
    label = STRATS.get(rec["strategy"], {}).get("label", rec["strategy"])
    won = rec["status"] == "won"
    line = "━━━━━━━━━━━━━━"
    icon = "⚽" if rec["sport"] == "football" else "🏀"
    lines = ["✅✅ TUTTU ✅✅" if won else "❌❌ TUTMADI ❌❌"]
    if MODE != "live":
        lines.append("🧪 DENEME (sinyal gönderilmemişti)")
    lines += [line,
              f"{icon} {rec['match']}",
              f"🏷 {label}",
              f"📊 Skor: {rec.get('signal_score', '-')} ➜ {rec.get('last_score', '-')}"]
    if rec["sport"] == "football":
        goals = rec["final_total"] - rec["base"]
        band = rec["band"]
        mid = (band[0] + band[1]) / 2
        pl = (mid - 1) * stake_tl() if won else -stake_tl()
        lines.append(f"🥅 Sinyalden sonra {goals} gol")
        lines.append(f"{'💰' if won else '💸'} Tahmini: {pl:+.0f} TL (oran {mid:.2f})")
    else:
        yon = "ÜST" if rec.get("direction") == "over" else "ALT"
        lines.append(f"📉 Tempo: {rec.get('seg_avg')} sayı/çeyrek (referans {rec.get('ref', 0):.0f}, beklenti {yon})")
        lines.append("ℹ️ Bahis sonucu değil, tempo ölçümüdür")
    same = [r for r in state["signals"].values()
            if r["strategy"] == rec["strategy"] and r["status"] in ("won", "lost")]
    w = sum(1 for r in same if r["status"] == "won")
    lines += [line, f"📈 Bu strateji: {w} ✅ / {len(same) - w} ❌ (%{100 * w / len(same):.0f})"]
    ok = send_telegram("\n".join(lines))
    if ok:
        log(f"Sonuç bildirimi gönderildi: {rec['match']} / {rec['strategy']} -> {rec['status']}")
    else:
        rec["result_sent"] = False
        log(f"Sonuç bildirimi gönderilemedi, sonraki turda tekrar denenecek: {rec['match']} / {rec['strategy']}")
    return ok


def settle(rec, final_total, state=None):
    if rec.get("status") in ("won", "lost", "void"):
        return
    rec["final_total"] = final_total
    rec["settled"] = datetime.now(timezone.utc).isoformat()
    base = rec.get("base", 0)
    if final_total < base:
        rec["status"] = "void"
        rec["result_sent"] = True
        return
    avg = (final_total - base) / max(rec.get("n", 1), 1)
    ref = rec.get("ref", 0.0)
    ok = avg > ref if rec.get("direction") == "over" else avg < ref
    rec["status"] = "won" if ok else "lost"
    rec["seg_avg"] = round(avg, 1)
    log(f"Sonuçlandı: {rec['match']} / {rec['strategy']} -> {rec['status']} (final toplam {final_total})")
    if state is not None:
        notify_result(state, rec)


def process_sport(state, sport):
    data = fetch(sport)
    if data is None:
        log(f"{sport}: veri alınamadı, tur atlandı")
        return
    parser = parse_basketball if sport == "basketball" else parse_football
    enabled = ENABLE_BASKETBALL if sport == "basketball" else ENABLE_FOOTBALL
    sdefs = [STRATS[sid] for sid in STRAT_ORDER
             if STRATS[sid]["sport"] == sport and sid not in DISABLED]

    seen, total_events = set(), 0
    for league, ev in iter_events(data, sport):
        total_events += 1
        p = parser(league, ev)
        if not p:
            continue
        seen.add(p["match_id"])

        for rec in state["signals"].values():
            if rec["match_id"] == p["match_id"] and rec["status"] == "pending":
                rec["last_total"] = p["total"]
                rec["last_score"] = f"{p['home']}-{p['away']}"
                rec["missing_runs"] = 0
                if p["final"]:
                    settle(rec, p["total"], state)

        if enabled and not p["final"] and not match_already_has_signal(state, p["match_id"]):
            for sd in sdefs:
                try:
                    res = sd["fn"](p)
                except Exception as exc:
                    log(f"Strateji hatası {sd['id']}: {exc}")
                    res = None
                if res:
                    stat_line = None
                    if sport == "football":
                        st = fetch_fb_stats(p.get("eid"))
                        ok_stat, reason = passes_fb_stat_filter(p, sd, st)
                        if not ok_stat:
                            log(f"İstatistik filtresi eledi: {p['match']} / {sd['id']} -> {reason}")
                            continue
                        stat_line = format_fb_stat_line(st)
                    if register_signal(state, p, sd, res, stat_line=stat_line):
                        break

    for rec in state["signals"].values():
        if rec["sport"] == sport and rec["status"] == "pending" and rec["match_id"] not in seen:
            rec["missing_runs"] += 1
            if rec["missing_runs"] >= MISSING_RUNS_TO_SETTLE:
                settle(rec, rec["last_total"], state)

    for rec in state["signals"].values():
        if rec["sport"] == sport and rec.get("status") in ("won", "lost") and not rec.get("result_sent"):
            notify_result(state, rec)

    log(f"{sport}: {total_events} canlı olay tarandı (İddaa filtresi aktif)")


# ------------------------------------------------------------------
# ÖZET
# ------------------------------------------------------------------
def summary(state):
    lines = [f"GÜNLÜK ÖZET ({MODE.upper()} modu)", ""]
    by = {}
    for rec in state["signals"].values():
        by.setdefault(rec["strategy"], []).append(rec)
    if not by:
        lines.append("Henüz kayıtlı sinyal yok.")
    for sid in sorted(by):
        if HIDE_DISABLED_IN_SUMMARY and sid in DISABLED:
            continue
        recs = by[sid]
        label = STRATS.get(sid, {}).get("label", sid)
        won = sum(1 for r in recs if r["status"] == "won")
        lost = sum(1 for r in recs if r["status"] == "lost")
        pend = sum(1 for r in recs if r["status"] == "pending")
        done = won + lost
        band = recs[0]["band"]
        rate_val = (100.0 * won / done) if done else None
        rate = f"%{rate_val:.0f}" if rate_val is not None else "-"
        lines.append(f"{label}")
        if recs[0]["sport"] == "football":
            mid = (band[0] + band[1]) / 2
            profit = (won * (mid - 1) - lost) * stake_tl()
            lines.append(f"  Tuttu {won} | Tutmadı {lost} | Bekleyen {pend}")
            lines.append(f"  İsabet {rate} (başa baş %{breakeven(band):.0f}) | K/Z {profit:+.0f} TL")
        else:
            lines.append(f"  Hipotez gerçekleşti {won} | Gerçekleşmedi {lost} | Bekleyen {pend}")
            lines.append(f"  Oran: %{rate.strip('%')} (bahis sonucu DEĞİL, çizgi bilinmiyor)"
                         if done else "  Henüz sonuç yok")
        if rate_val is not None and done >= 4 and rate_val < breakeven(band):
            lines.append(f"  Karne uyarısı: başa baş %{breakeven(band):.0f} altında.")
        elif 0 < done < 30:
            lines.append(f"  Örnek az ({done}); güvenmeyin.")
    send_telegram("\n".join(lines))


# ------------------------------------------------------------------
def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    state = load_state()
    if cmd == "summary":
        summary(state)
    elif cmd == "test":
        success = send_telegram("🤖 *Test Başarılı!* v2.9.5 aktif: İlk yarı 0-0 baskı kurgusu ve GOL OLUR / GOL OLMAZ ayrımı devrede.")
        if success:
            log("Test mesajı Telegram'a başarıyla gönderildi!")
        else:
            log("Test mesajı gönderilemedi!")
    else:
        active = [s for s in STRATS.values() if s["id"] not in DISABLED]
        log(f"Mod: {MODE} | Aktif strateji: {len(active)} | "
            f"Basketbol: {ENABLE_BASKETBALL} | Futbol: {ENABLE_FOOTBALL}")
        for sport, enabled in (("basketball", ENABLE_BASKETBALL), ("football", ENABLE_FOOTBALL)):
            pending = any(r["sport"] == sport and r["status"] == "pending"
                          for r in state["signals"].values())
            if enabled or pending:
                process_sport(state, sport)
                time.sleep(1)
    save_state(state)


if __name__ == "__main__":
    main()
