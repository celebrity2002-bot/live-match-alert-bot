#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canlı Sinyal Botu v2 - GitHub Actions sürümü (Futbol & Basketbol İddaa Bülten Filtreli)
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
DEBUG_PATH = BASE / "debug_sample.json"

TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def env_num(name, default, cast=float):
    try:
        return cast(os.getenv(name, "").strip() or default)
    except ValueError:
        return cast(default)


MODE = (os.getenv("BOT_MODE", "paper") or "paper").strip().lower()   # paper | live
BANKROLL = env_num("BANKROLL_TL", 2000)
STAKE_PCT = env_num("STAKE_PCT", 1.0)
ENABLE_BASKETBALL = os.getenv("ENABLE_BASKETBALL", "1") == "1"
ENABLE_FOOTBALL = os.getenv("ENABLE_FOOTBALL", "1") == "1"
DISABLED = {x.strip().upper() for x in os.getenv("DISABLE_STRATEGIES", "").split(",") if x.strip()}
MAX_LIVE_PER_MATCH = env_num("MAX_LIVE_PER_MATCH", 2, int)
SEND_RESULTS = (os.getenv("SEND_RESULTS", "on") or "on").strip().lower()

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

# Basketbol için İddaa bülteni odaklı izin verilen anahtar kelimeler (EuroLeague, NBA, BSL, ACB, vb.)
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

# Futbol eşikleri
FB_LATE_MIN = env_num("FB_LATE_MIN", 65, int)
FB_LATE_MAX = env_num("FB_LATE_MAX", 80, int)
FB_OPEN_MIN_GOALS = env_num("FB_OPEN_MIN_GOALS", 2, int)

MISSING_RUNS_TO_SETTLE = 3

URLS = {
    "basketball": "https://prod-public-api.livescore.com/v1/api/app/live/basketball/3?MD=1",
    "football": "https://prod-public-api.livescore.com/v1/api/app/live/soccer/1?MD=1",
}
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


def iter_events(data, sport="football"):
    keywords = ALLOWED_BASKETBALL_KEYWORDS if sport == "basketball" else ALLOWED_FOOTBALL_KEYWORDS
    for stage in (data or {}).get("Stages", []) or []:
        league = " ".join(
            x for x in (str(stage.get("Cnm", "")).strip(), str(stage.get("Snm", "")).strip()) if x
        )
        # İddaa bülten filtresi kontrolü (Branşa özel)
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


# ------------------------------------------------------------------
# STRATEJİ KAYIT DEFTERİ
# ------------------------------------------------------------------
STRATS = {}


def strat(sid, sport, label, title, pick, band):
    def deco(fn):
        STRATS[sid] = dict(id=sid, sport=sport, label=label, title=title,
                           pick=pick, band=band, fn=fn)
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
    return {
        "sport": "football",
        "match_id": f"fb_{ev.get('Eid')}",
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


@strat("FB_GEC_GOL", "football",
       f"Gol baskısı ({FB_LATE_MIN}-{FB_LATE_MAX}', fark ≤1, {FB_OPEN_MIN_GOALS}+ gol)",
       "FUTBOL ALARMI (GOLLÜ MAÇ, GOL BASKISI)", "Sıradaki Gol Olur / Canlı Üst", (1.40, 1.70))
def fb_gec_gol(p):
    if fb_in(p, FB_LATE_MIN, FB_LATE_MAX) and p["diff"] <= 1 and p["total"] >= FB_OPEN_MIN_GOALS:
        return fb_res(p, fb_line(p))


@strat("FB_IY2_00", "football", "0-0 ikinci yarı başı gol",
       "FUTBOL ALARMI (0-0, 2. YARI GOL)", "2. Yarıda Gol Olur / Canlı Üst", (1.40, 1.60))
def fb_iy2_00(p):
    if (p["ht"] or fb_in(p, 46, 55)) and p["total"] == 0:
        return fb_res(p, fb_line(p))


@strat("FB_00_60_70", "football", "0-0 ve 60-70. dakika",
       "FUTBOL ALARMI (0-0, 60-70' GOL)", "Maçta Gol Olur / Canlı Üst", (1.60, 2.00))
def fb_00_60_70(p):
    if fb_in(p, 60, 70) and p["total"] == 0:
        return fb_res(p, fb_line(p))


@strat("FB_TEK_FARK_70", "football", f"Tek farkla önde, {FB_LATE_MIN}-{FB_LATE_MAX}'",
       "FUTBOL ALARMI (TEK FARK, EK GOL)", "Ek Gol Olur / Canlı Üst", (1.45, 1.85))
def fb_tek_fark(p):
    if fb_in(p, FB_LATE_MIN, FB_LATE_MAX) and p["diff"] == 1:
        return fb_res(p, fb_line(p))


@strat("FB_11_IY2", "football", "1-1 ikinci yarı başı",
       "FUTBOL ALARMI (1-1, 2. YARI GOL)", "Bir Gol Daha Olur / Canlı Üst", (1.45, 1.75))
def fb_11_iy2(p):
    if (p["ht"] or fb_in(p, 46, 60)) and p["home"] == 1 and p["away"] == 1:
        return fb_res(p, fb_line(p))


@strat("FB_BERABERLIK_GEC", "football", f"Beraberlik (1-1+) {FB_LATE_MIN}-{FB_LATE_MAX}'",
       "FUTBOL ALARMI (BERABERLİK, GOL BASKISI)", "Sıradaki Gol Olur / Canlı Üst", (1.40, 1.75))
def fb_beraberlik(p):
    if fb_in(p, FB_LATE_MIN, FB_LATE_MAX) and p["home"] == p["away"] and p["total"] >= 2:
        return fb_res(p, fb_line(p))


@strat("FB_COK_GOLLU_ERKEN", "football", "Erken çok gol (25-40', 3+ gol)",
       "FUTBOL ALARMI (GOLLÜ MAÇ)", "Ek Gol Olur / Canlı Üst", (1.50, 1.90))
def fb_cok_gollu(p):
    if fb_in(p, 25, 40) and p["total"] >= 3:
        return fb_res(p, fb_line(p))


@strat("FB_GERIDEN_FARK2", "football", "2 gol fark, 55-80'",
       "FUTBOL ALARMI (2 GOL FARK, BASKI)", "Sıradaki Gol Olur / Canlı Üst", (1.60, 2.10))
def fb_fark2(p):
    if fb_in(p, 55, 80) and p["diff"] == 2:
        return fb_res(p, fb_line(p))


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


@strat("BB_TEMPO_DUSUSU_ALT", "basketball", "Tempo düşüşü ALT (Q1 yüksek)",
       "BASKETBOL ALARMI (TEMPO DÜŞÜŞÜ ALT)", "Canlı Toplam Sayı ALT", (1.45, 1.55))
def bb_tempo_dususu(p):
    q1 = p["q"][0]
    if p["period"] == 2 and q1 is not None and q1 >= BB_Q1_HIGH \
            and 0 <= p["total"] - q1 <= BB_Q2_MAX_POINTS:
        return {"direction": "under", "base": q1, "n": 3, "ref": float(q1),
                "detail": f"Süre: 2. Çeyrek Başı | Toplam Skor: {p['total']}\n"
                          f"1. Çeyrek Toplamı: {q1} sayı"}


@strat("BB_Q1_DUSUK_UST", "basketball", "Tempo yükselişi ÜST (Q1 düşük)",
       "BASKETBOL ALARMI (TEMPO YÜKSELİŞİ ÜST)", "Canlı Toplam Sayı ÜST", (1.55, 1.90))
def bb_q1_dusuk(p):
    q1 = p["q"][0]
    if p["period"] == 2 and q1 is not None and q1 <= BB_Q1_LOW \
            and 0 <= p["total"] - q1 <= BB_Q2_MAX_POINTS:
        return {"direction": "over", "base": q1, "n": 3, "ref": float(q1),
                "detail": f"Süre: 2. Çeyrek Başı | Toplam Skor: {p['total']}\n"
                          f"1. Çeyrek Toplamı: {q1} sayı"}


@strat("BB_HT_YUKSEK_ALT", "basketball", "Devre arası yüksek skor ALT",
       "BASKETBOL ALARMI (DEVRE ARASI YÜKSEK SKOR ALT)", "Canlı Toplam Sayı ALT", (1.50, 1.80))
def bb_ht_yuksek(p):
    if p["ht"] and p["total"] >= BB_HT_HIGH:
        return {"direction": "under", "base": p["total"], "n": 2, "ref": p["total"] / 2.0,
                "detail": f"Devre Arası | İlk Yarı Toplamı: {p['total']} sayı "
                          f"({p['home']}-{p['away']})"}


@strat("BB_HT_DUSUK_UST", "basketball", "Devre arası düşük skor ÜST",
       "BASKETBOL ALARMI (DEVRE ARASI DÜŞÜK SKOR ÜST)", "Canlı Toplam Sayı ÜST", (1.50, 1.80))
def bb_ht_dusuk(p):
    if p["ht"] and 0 < p["total"] <= BB_HT_LOW:
        return {"direction": "over", "base": p["total"], "n": 2, "ref": p["total"] / 2.0,
                "detail": f"Devre Arası | İlk Yarı Toplamı: {p['total']} sayı "
                          f"({p['home']}-{p['away']})"}


def _q4_info(p):
    if p["period"] != 4 or any(x is None for x in p["q"][:3]):
        return None
    first3 = sum(p["q"][:3])
    q4_pts = p["total"] - first3
    if 0 <= q4_pts <= BB_Q4_MAX_POINTS:
        return first3, q4_pts
    return None


@strat("BB_Q4_YAKIN_UST", "basketball", "4. çeyrek başı yakın skor ÜST",
       "BASKETBOL ALARMI (4. ÇEYREK YAKIN MAÇ ÜST)", "Canlı Toplam Sayı ÜST", (1.60, 2.00))
def bb_q4_yakin(p):
    info = _q4_info(p)
    if info and p["diff"] <= 3:
        first3, q4_pts = info
        return {"direction": "over", "base": first3, "n": 1, "ref": first3 / 3.0,
                "detail": f"Süre: 4. Çeyrek Başı | Skor: {p['home']}-{p['away']} "
                          f"(fark {p['diff']})\nİlk 3 çeyrek ortalaması: {first3 / 3:.1f} sayı"}


@strat("BB_Q4_FARK_ALT", "basketball", "4. çeyrek başı büyük fark ALT",
       "BASKETBOL ALARMI (4. ÇEYREK BÜYÜK FARK ALT)", "Canlı Toplam Sayı ALT", (1.60, 1.95))
def bb_q4_fark(p):
    info = _q4_info(p)
    if info and p["diff"] >= 15:
        first3, q4_pts = info
        return {"direction": "under", "base": first3, "n": 1, "ref": first3 / 3.0,
                "detail": f"Süre: 4. Çeyrek Başı | Skor: {p['home']}-{p['away']} "
                          f"(fark {p['diff']})\nİlk 3 çeyrek ortalaması: {first3 / 3:.1f} sayı"}


# ------------------------------------------------------------------
# SİNYAL OLUŞTURMA / SONUÇLANDIRMA
# ------------------------------------------------------------------
def build_message(p, sd, res):
    band = sd["band"]
    line = "━━━━━━━━━━━━━━"
    icon = "⚽" if p["sport"] == "football" else "🏀"
    detail = res["detail"].split("\n")
    lines = [f"🚨 {sd['title']}", line, f"{icon} {p['match']}"]
    if p.get("league"):
        lines.append(f"🏆 {p['league']}")
    lines.append(f"⏱ {detail[0]}")
    lines += [f"📊 {d}" for d in detail[1:]]
    lines += [line,
              f"🎯 OYNA: {sd['pick']}",
              f"📈 Oran bandı: {band[0]:.2f} - {band[1]:.2f}",
              f"💰 Tutar: {stake_tl()} TL (Min: {MIN_STAKE_TL} TL)",
              f"🎲 Başa baş isabet: %{breakeven(band):.0f}",
              "",
              "⚠️ Oran bandın dışındaysa OYNAMAYIN"]
    return "\n".join(lines)


def register_signal(state, p, sd, res):
    key = f"{p['match_id']}|{sd['id']}"
    if key in state["signals"]:
        return False
    rec = {
        "key": key, "sport": p["sport"], "match_id": p["match_id"], "match": p["match"],
        "league": p["league"], "strategy": sd["id"], "pick": sd["pick"], "band": list(sd["band"]),
        "created": datetime.now(timezone.utc).isoformat(),
        "status": "pending", "missing_runs": 0, "last_total": p["total"], "sent": False,
        "direction": res["direction"], "base": res["base"], "n": res["n"], "ref": res["ref"],
        "signal_score": f"{p['home']}-{p['away']}", "last_score": f"{p['home']}-{p['away']}",
    }
    state["signals"][key] = rec
    if MODE == "live":
        sent_for_match = sum(1 for r in state["signals"].values()
                             if r["match_id"] == p["match_id"] and r.get("sent"))
        if sent_for_match < MAX_LIVE_PER_MATCH:
            rec["sent"] = send_telegram(build_message(p, sd, res))
        else:
            log(f"Bu maç için mesaj sınırına ulaşıldı, sadece kaydedildi: {p['match']} / {sd['id']}")
    else:
        log(f"[PAPER] Kaydedildi: {p['match']} / {sd['id']}")
    return True


def notify_result(state, rec):
    if SEND_RESULTS == "off":
        return
    if MODE == "live" and not rec.get("sent"):
        return
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
    send_telegram("\n".join(lines))


def settle(rec, final_total, state=None):
    rec["final_total"] = final_total
    rec["settled"] = datetime.now(timezone.utc).isoformat()
    base = rec.get("base", 0)
    if final_total < base:
        rec["status"] = "void"
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
    sdefs = [s for s in STRATS.values() if s["sport"] == sport and s["id"] not in DISABLED]

    seen, total_events, raw_samples = set(), 0, []
    for league, ev in iter_events(data, sport):
        total_events += 1
        if len(raw_samples) < 3:
            raw_samples.append(ev)
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

        if enabled and not p["final"]:
            for sd in sdefs:
                try:
                    res = sd["fn"](p)
                except Exception as exc:
                    log(f"Strateji hatası {sd['id']}: {exc}")
                    res = None
                if res:
                    register_signal(state, p, sd, res)

    for rec in state["signals"].values():
        if rec["sport"] == sport and rec["status"] == "pending" and rec["match_id"] not in seen:
            rec["missing_runs"] += 1
            if rec["missing_runs"] >= MISSING_RUNS_TO_SETTLE:
                settle(rec, rec["last_total"], state)

    if os.getenv("DEBUG_DUMP") == "1" and raw_samples:
        dump = {"top_level_keys": list(data.keys()) if isinstance(data, dict) else None,
                "events": raw_samples}
        (BASE / f"debug_sample_{sport}.json").write_text(
            json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
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
        recs = by[sid]
        label = STRATS.get(sid, {}).get("label", sid)
        won = sum(1 for r in recs if r["status"] == "won")
        lost = sum(1 for r in recs if r["status"] == "lost")
        pend = sum(1 for r in recs if r["status"] == "pending")
        done = won + lost
        band = recs[0]["band"]
        rate = f"%{100 * won / done:.0f}" if done else "-"
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
        if 0 < done < 30:
            lines.append(f"  Örnek az ({done}); güvenmeyin.")
    send_telegram("\n".join(lines))


# ------------------------------------------------------------------
def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    state = load_state()
    if cmd == "summary":
        summary(state)
    elif cmd == "test":
        success = send_telegram("🤖 *Test Başarılı!* Futbol ve Basketbol için İddaa bülten filtreleri aktifleşti.")
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
