import json
import os
import time
import html
from datetime import datetime, timezone
import requests
from config import *

STATE = "state/sent.json"


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    cut = time.time() - 30 * 86400
    st = {k: v for k, v in st.items() if v > cut}
    os.makedirs("state", exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(st, f)


def _day(ts):
    # +12h so the date matches the exchange candle day
    return datetime.fromtimestamp(ts + 43200, tz=timezone.utc).strftime("%d %b %Y")


def caption(s):
    e = "🟢" if s["side"] == "long" else "🔴"
    kind = ("Sell-side sweep -> LONG" if s["side"] == "long"
            else "Buy-side sweep -> SHORT")
    risk = abs(s["entry"] - s["sl"])
    rr = lambda t: abs(t - s["entry"]) / risk
    return (
        f"{e} <b>{html.escape(s['symbol'])}</b> | {s['tf'].upper()} | "
        f"Grade {s['grade']} ({s['score']})\n"
        f"{kind} + confirmation candle closed\n"
        f"Sweep candle: {_day(s['start'])}\n"
        f"Confirmed by candle: {_day(s['conf_start'])}\n"
        f"Swept level: {fmt(s['level'])} | wick extreme: {fmt(s['extreme'])}\n\n"
        f"Entry: {fmt(s['entry'])}\n"
        f"SL: {fmt(s['sl'])}\n"
        f"TP1: {fmt(s['tp1'])} ({rr(s['tp1']):.1f}R)\n"
        f"TP2: {fmt(s['tp2'])} ({rr(s['tp2']):.1f}R)\n"
        f"TP3: {fmt(s['tp3'])} ({rr(s['tp3']):.1f}R)\n\n"
        f"{' | '.join(s['notes'])} | Depth {s['depth']:.2f} ATR | "
        f"RSI {s['rsi']:.0f}"
    )


def send_photo(img, cap):
    if not TG_TOKEN or not TG_CHAT:
        print("Telegram secrets missing")
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
        data={"chat_id": TG_CHAT, "caption": cap[:1024], "parse_mode": "HTML"},
        files={"photo": ("chart.png", img)}, timeout=60)
    if not r.ok:
        print("TG error", r.text[:200])
    return r.ok


def send_text(text):
    if not TG_TOKEN or not TG_CHAT:
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data={"chat_id": TG_CHAT, "text": text[:4000], "parse_mode": "HTML"},
        timeout=30)
    return r.ok
