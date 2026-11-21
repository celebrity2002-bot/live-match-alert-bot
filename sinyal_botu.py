#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canlı Sinyal Botu v2.6 - Seçici 2. Yarı Penceresi + Aday Maç İstatistik Filtresi
"""
import json
import os
import re
import sys
import time
import random
from datetime import datetime, timezone
from pathlib import Path

import requests

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
MIN_TOTAL_XG = env_num("MIN_TOTAL_XG", 0.35, float)

# %60 altında kalan stratejiler varsayılan pasif; az verili %100'ler açık tutuldu
DEFAULT_DISABLED = {
    "OZEL_FB_BASKI_SIKISMA",
    "FB_TEK_FARK_70",
    "FB_GERIDEN_FARK2",
    "BB_Q4_YAKIN_UST",
}
ENV_DISABLED = {x.strip().upper() for x in os.getenv("DISABLE_STRATEGIES", "").split(",") if x.strip()}
DISABLED = DEFAULT_DISABLED | ENV_DISABLED

# Her maçtan (futbol veya basketbol) en fazla 1 sinyal
MAX_LIVE_PER_MATCH = env_num("MAX_LIVE_PER_MATCH", 1, int)
SEND_RESULTS = (os.getenv("SEND_RESULTS", "on") or "on").strip().lower()
HIDE_DISABLED_IN_SUMMARY = os.getenv("HIDE_DISABLED_IN_SUMMARY", "1") == "1"

# Minimum bahis tutarı kuralı (En az 50 TL)
MIN_STAKE_TL = env_num("MIN_STAKE_TL", 50, int)

# Futbol için İddaa bülteni odaklı izin verilen anahtar kelimeler
default_football_keywords = (
    "turkey,england,spain,italy,germany,france,netherlands,portugal,"
    "uefa,champions league,europa league,conference league,brazil,argentina,"
    "mls,saudi arabia,greece,belgium,austria,switzerland,colombia,mexico"
)
ALLOWED_FOOTBALL_KEYWORDS = {
    x.strip().lower()
    for x in os.getenv("ALLOWED_FOOTBALL_KEYWORDS", default_football_keywords).split(",")
    if x.strip()
}

# Basketbol için İddaa bülteni odaklı izin verilen anahtar kelimeler
default_basketball_keywords = (
    "euroleague,eurocup,champions league,nba,wnba,ncaa,turkey,super lig,tbl,bsl,"
    "spain,acb,endesa,italy,germany,bundesliga,france,lnb,greece,aba,vtb"
)
ALLOWED_BASKETBALL_KEYWORDS = {
    x.strip().lower()
    for x in os.getenv("ALLOWED_BASKETBALL_KEYWORDS", default_basketball_keywords).split(",")
    if x.strip()
}

# Basketbol eşikleri
BB_Q1_HIGH = env_num("BB_Q1_HIGH", 50, int)
BB_Q1_LOW = env_num("BB_Q1_LOW", 36, int)
BB_Q2_MAX_POINTS = env_num("BB_Q2_MAX_POINTS", 15, int)
BB_Q4_MAX_POINTS = env_num("BB_Q4_MAX_POINTS", 8, int)
BB_HT_HIGH = env_num("BB_HT_HIGH", 95, int)
BB_HT_LOW = env_num("BB_HT_LOW", 70, int)

# Futbol eşikleri (devre geçişi riskini azaltmak için 2. yarı başı 46-48' penceresi)
FB_LATE_MIN = env_num("FB_LATE_MIN", 65, int)
FB_LATE_MAX = env_num("FB_LATE_MAX", 80, int)
FB_OPEN_MIN_GOALS = env_num("FB_OPEN_MIN_GOALS", 2, int)
FB_IY2_MIN_MIN = env_num("FB_IY2_MIN_MIN", 46, int)
FB_IY2_MAX_MIN = env_num("FB_IY2_MAX_MIN", 48, int)
FB_EARLY_HIGH_MIN_START = env_num("FB_EARLY_HIGH_MIN_START", 24, int)
FB_EARLY_HIGH_MIN_END = env_num("FB_EARLY_HIGH_MIN_END", 37, int)

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

        shon1, shon2 = num(t1.get("Shon")) or 0, num(t2.get("Shon")) or 0
        shof1, shof2 = num(t1.get("Shof")) or 0, num(t2.get("Shof")) or 0
        cos1, cos2 = num(t1.get("Cos")) or 0, num(t2.get("Cos")) or 0
        ycs1, ycs2 = num(t1.get("Ycs")) or 0, num(t2.get("Ycs")) or 0
        rcs1, rcs2 = num(t1.get("Rcs")) or 0, num(t2.get("Rcs")) or 0
        pss1, pss2 = num(t1.get("Pss")), num(t2.get("Pss"))

        return {
            "xg_total": total_xg,
            "xg1": xg1,
            "xg2": xg2,
            "sot_total": shon1 + shon2,
            "shots_total": shon1 + shon2 + shof1 + shof2,
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
    parts.append(f"İsabetli Şut {st['sot_total']}/{st['shots_total']}")
    parts.append(f"Korner {st['corners_total']}")
    if st.get("rc_total", 0) > 0:
        parts.append(f"Kırmızı Kart {st['rc_total']}")
    elif st.get("yc_total", 0) > 0:
        parts.append(f"Sarı Kart {st['yc_total']}")
    return " | ".join(parts)


def passes_fb_stat_filter(p, sd, st):
    if not ENABLE_STAT_FILTER or not st:
        return True, None
    # Kısır / ölü maç koruması: çok düşük xG ve çok az toplam şut + korner
    xg_tot = st.get("xg_total")
    activity = st.get("shots_total", 0) + st.get("corners_total", 0)
    if xg_tot is not None and xg_tot < MIN_TOTAL_XG and activity <= 4:
        return False, f"Kısır maç filtresi (xG {xg_tot:.2f}, şut+korner {activity})"
    return True, None


def iter_events(data, sport="football"):
    keywords = ALLOWED_BASKETBALL_KEYWORDS if sport == "basketball" else ALLOWED_FOOTBALL_KEYWORDS
    for stage in (data or {}).get("Stages", []) or []:
        league = " ".join(
            x for x in (str(stage.get("Cnm", "")).strip(), str(stage.get("Snm", "")).strip()) if x
        )
        if keywords:
            l_lower = league.lower()
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


def breakeven(band):
    return 100.0 / ((band[0] + band[1]) / 2)


def stake_tl():
    hesaplanan = round(BANKROLL * STAKE_PCT / 100.0)
    return max(MIN_STAKE_TL, hesaplanan)


def decay_risk_note(p):
    if p["sport"] == "football":
        if p.get("minute") is not None and p["minute"] >= 47:
            return "Yüksek — 1.05-1.15 bandına indiyse veya market kapalıysa PAS"
        return "Orta — oran tam bandındaysa değerlendir, düşükse PAS"
    return "Orta — çizgi/oran bandı uyuşmuyorsa PAS"


def form_note(state, sid, band, sport):
    same = [r for r in state.get("signals", {}).values()
            if r.get("strategy") == sid and r.get("status") in ("won", "lost")]
    done = len(same)
    if done == 0:
        hist = "İlk sinyal | Az örneklem"
    else:
        won = sum(1 for r in same if r.get("status") == "won")
        rate = 100.0 * won / done
        sample_tag = "Az örneklem" if done < 20 else f"{done} sinyal"
        hist = f"Geçmiş {won}/{done} (%{rate:.0f}) | {sample_tag}"

    band_txt = f"Oran {band[0]:.2f}-{band[1]:.2f} bandındaysa değerlendir"
    action = f"{band_txt} (çizgi sende)" if sport == "basketball" else f"{band_txt} (farklı çizgiye sapma, bandın dışındaysa pas geç)"
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


def fb_res(p, detail):
    return {"detail": detail, "direction": "over", "base": p["total"], "n": 1, "ref": 0.0}


def fb_in(p, lo, hi):
    return p["minute"] is not None and lo <= p["minute"] <= hi


def fb_line(p):
    t = "Devre Arası" if p["ht"] else f"Dakika: {p['minute']}'"
    return f"{t} | Skor: {p['home']}-{p['away']}"


@strat("FB_IY2_00", "football", f"0-0 2. yarı başı gol ({FB_IY2_MIN_MIN}-{FB_IY2_MAX_MIN}')",
       "FUTBOL ALARMI (0-0, 2. YARI BAŞI GOL)", "2. Yarıda Gol Olur / Canlı Üst", (1.45, 1.70))
def fb_iy2_00(p):
    if fb_in(p, FB_IY2_MIN_MIN, FB_IY2_MAX_MIN) and p["total"] == 0:
        return fb_res(p, f"{fb_line(p)}\n2. yarı başı taze pencere — sadece bantta ise gir")


@strat("FB_COK_GOLLU_ERKEN", "football", f"Erken çok gol ({FB_EARLY_HIGH_MIN_START}-{FB_EARLY_HIGH_MIN_END}', 3+ gol)",
       "FUTBOL ALARMI (GOLLÜ MAÇ)", "Ek Gol Olur / Canlı Üst", (1.50, 1.90))
def fb_cok_gollu(p):
    if fb_in(p, FB_EARLY_HIGH_MIN_START, FB_EARLY_HIGH_MIN_END) and p["total"] >= 3:
        return fb_res(p, f"{fb_line(p)}\nErken gol ivmesi — oran çökmeden kontrol et")


@strat("FB_GERIDEN_FARK2", "football", "2 gol fark, 55-80'",
       "FUTBOL ALARMI (2 GOL FARK, BASKI)", "Sıradaki Gol Olur / Canlı Üst", (1.60, 2.10))
def fb_fark2(p):
    if fb_in(p, 55, 80) and p["diff"] == 2:
        return fb_res(p, f"{fb_line(p)}\n2 gol fark baskısı — reaksiyon / ek gol ihtimali")


@strat("FB_TEK_FARK_70", "football", f"Tek farkla önde, {FB_LATE_MIN}-{FB_LATE_MAX}'",
       "FUTBOL ALARMI (TEK FARK, EK GOL)", "Ek Gol Olur / Canlı Üst", (1.45, 1.85))
def fb_tek_fark(p):
    if fb_in(p, FB_LATE_MIN, FB_LATE_MAX) and p["diff"] == 1:
        return fb_res(p, f"{fb_line(p)}\nTek fark üstünlüğü — risk/açık oyun ihtimali")


@strat("OZEL_FB_BASKI_SIKISMA", "football", "Görünmeyen Baskı ve Sıkışma (Özel Sinyal)",
       "🔔 ÖZEL SİNYAL (Gölge Avı)", "Sıradaki Gol Olur / Canlı Üst", (1.65, 2.05), is_special=True)
def ozel_fb_baski(p):
    if fb_in(p, 65, 78) and p["total"] <= 1:
        return {
            "detail": f"Dakika: {p['minute']}' | Skor: {p['home']}-{p['away']}\n"
                      f"Analiz: Piyasa maçın kısır geçeceğini sanıp 'Alt' oranlarını şişirdi. Sıkışma tavan yaptı.",
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
       "🔔 ÖZEL SİNYAL (Gölge Avı)", "Canlı Toplam Sayı ALT", (1.70, 2.10), is_special=True)
def ozel_bb_bench(p):
    info = _q4_info(p)
    if info and p["total"] > 140:
        first3, _ = info
        return {
            "detail": f"Süre: 4. Çeyrek Başı | Skor: {p['home']}-{p['away']}\n"
                      f"Analiz: Fiziksel düşüş ve rotasyon tıkanması saptandı. Piyasa yanıltıcı şekilde ÜST bekliyor.",
            "direction": "under", "base": first3, "n": 1, "ref": first3 / 3.0
        }
    return None


@strat("BB_TEMPO_DUSUSU_ALT", "basketball", "Tempo düşüşü ALT (Q1 yüksek)",
       "BASKETBOL ALARMI (TEMPO DÜŞÜŞÜ ALT)", "Canlı Toplam Sayı ALT", (1.45, 1.55))
def bb_tempo_dususu(p):
    q1 = p["q"][0]
    if p["period"] == 2 and q1 is not None and q1 >= BB_Q1_HIGH \
            and 0 <= p["total"] - q1 <= BB_Q2_MAX_POINTS:
        return {"direction": "under", "base": q1, "n": 3, "ref": float(q1),
                "detail": f"Süre: 2. Çeyrek Başı | Toplam Skor: {p['total']}\n1. Çeyrek Toplamı: {q1} sayı"}


@strat("BB_HT_DUSUK_UST", "basketball", "Devre arası düşük skor ÜST",
       "BASKETBOL ALARMI (DEVRE ARASI DÜŞÜK SKOR ÜST)", "Canlı Toplam Sayı ÜST", (1.50, 1.80))
def bb_ht_dusuk(p):
    if p["ht"] and 0 < p["total"] <= BB_HT_LOW:
        return {"direction": "over", "base": p["total"], "n": 2, "ref": p["total"] / 2.0,
                "detail": f"Devre Arası | İlk Yarı Toplamı: {p['total']} sayı ({p['home']}-{p['away']})"}


@strat("BB_Q1_DUSUK_UST", "basketball", "Tempo yükselişi ÜST (Q1 düşük)",
       "BASKETBOL ALARMI (TEMPO YÜKSELİŞİ ÜST)", "Canlı Toplam Sayı ÜST", (1.55, 1.90))
def bb_q1_dusuk(p):
    q1 = p["q"][0]
    if p["period"] == 2 and q1 is not None and q1 <= BB_Q1_LOW \
            and 0 <= p["total"] - q1 <= BB_Q2_MAX_POINTS:
        return {"direction": "over", "base": q1, "n": 3, "ref": float(q1),
                "detail": f"Süre: 2. Çeyrek Başı | Toplam Skor: {p['total']}\n1. Çeyrek Toplamı: {q1} sayı"}


@strat("BB_Q4_FARK_ALT", "basketball", "4. çeyrek başı büyük fark ALT",
       "BASKETBOL ALARMI (4. ÇEYREK BÜYÜK FARK ALT)", "Canlı Toplam Sayı ALT", (1.60, 1.95))
def bb_q4_fark(p):
    info = _q4_info(p)
    if info and p["diff"] >= 15:
        first3, _ = info
        return {"direction": "under", "base": first3, "n": 1, "ref": first3 / 3.0,
                "detail": f"Süre: 4. Çeyrek Başı | Skor: {p['home']}-{p['away']} (fark {p['diff']})\nİlk 3 çeyrek ortalaması: {first3 / 3:.1f} sayı"}


@strat("BB_Q4_YAKIN_UST", "basketball", "4. çeyrek başı yakın skor ÜST",
       "BASKETBOL ALARMI (4. ÇEYREK YAKIN MAÇ ÜST)", "Canlı Toplam Sayı ÜST", (1.60, 2.00))
def bb_q4_yakin(p):
    info = _q4_info(p)
    if info and p["diff"] <= 3:
        first3, _ = info
        return {"direction": "over", "base": first3, "n": 1, "ref
