"""
MEXC perpetual scanner - 4H squeeze + breakout (GitHub Actions version)

Pattern: long drop -> EMA 6/12/20 squeezed in a tight base -> big green candle
closing above all 3 EMAs. Closed 4H candles only. Chart photo sent to Telegram.
Same pair is alerted at most once per 24h (counted by signal candle).
"""
import os, io, json, time, requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from concurrent.futures import ThreadPoolExecutor, as_completed

# ------------------------- SETTINGS -------------------------
INTERVAL      = "Hour4"
INTERVAL_SEC  = 4 * 3600
INTERVAL_NAME = "4H"
CANDLES       = 150

EMA_FAST, EMA_MID, EMA_SLOW = 6, 12, 20
TREND_LOOKBACK = 100
SQUEEZE_BARS   = 12

# Which grades send a Telegram alert. Override with repo variable ALERT_GRADES (e.g. "A")
ALERT_GRADES = [g.strip().upper() for g in (os.getenv("ALERT_GRADES") or "A,B").split(",") if g.strip()]

MIN_24H_VOL_USDT = 0        # 0 = scan ALL pairs
WORKERS          = 8
MAX_ALERTS       = 15       # max alerts per run
COOLDOWN_HOURS   = 24       # same pair only once per 24h
STATE_FILE       = "state_squeeze.json"

# Grade A thresholds (strict)
A_BODY_X, A_BODY_PCT   = 2.0, 2.0
A_DROP_PCT, A_SQUEEZE  = 30.0, 4.0
A_VOL_X, A_CLOSE_POS   = 1.5, 0.70

# Grade B thresholds (loose)
B_BODY_X, B_BODY_PCT   = 1.5, 1.5
B_DROP_PCT, B_SQUEEZE  = 20.0, 6.0
# ------------------------------------------------------------

BASE = "https://contract.mexc.com/api/v1/contract"
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})


# ------------------------- DATA -------------------------
def get_symbols():
    r = session.get(f"{BASE}/detail", timeout=25).json()
    return sorted(c["symbol"] for c in r["data"]
                  if c.get("quoteCoin") == "USDT" and c.get("state") == 0)


def get_volumes():
    try:
        r = session.get(f"{BASE}/ticker", timeout=25).json()
        return {t["symbol"]: float(t.get("amount24", 0)) for t in r["data"]}
    except Exception:
        return {}


def get_klines(symbol):
    end = int(time.time())
    start = end - INTERVAL_SEC * CANDLES
    for attempt in range(3):
        try:
            resp = session.get(f"{BASE}/kline/{symbol}",
                               params={"interval": INTERVAL, "start": start, "end": end},
                               timeout=20)
            if resp.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            d = resp.json().get("data")
            if not d or not d.get("time"):
                return None
            df = pd.DataFrame({
                "ts":    [int(x) for x in d["time"]],
                "open":  [float(x) for x in d["open"]],
                "high":  [float(x) for x in d["high"]],
                "low":   [float(x) for x in d["low"]],
                "close": [float(x) for x in d["close"]],
                "vol":   [float(x) for x in d["vol"]],
            })
            df["time"] = pd.to_datetime(df["ts"], unit="s")
            return df.sort_values("ts").reset_index(drop=True)
        except Exception:
            time.sleep(0.7)
    return None


def add_emas(df):
    df["e6"]  = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["e12"] = df["close"].ewm(span=EMA_MID,  adjust=False).mean()
    df["e20"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    return df


# ------------------------- ANALYSIS -------------------------
def analyse(symbol, force=False):
    full = get_klines(symbol)
    if full is None or len(full) < 60:
        return None

    # closed candles only (drop the one still forming)
    now = time.time()
    closed = full[full["ts"] + INTERVAL_SEC <= now].reset_index(drop=True)
    if len(closed) < 60:
        return None

    df = add_emas(closed.copy())
    last, prev = df.iloc[-1], df.iloc[-2]
    top_ema = max(last.e6, last.e12, last.e20)

    body = last.close - last.open
    green_above = body > 0 and last.close > top_ema
    if not green_above and not force:
        return None

    body_pct = body / last.open * 100 if last.open > 0 else 0
    avg_body = (df["close"] - df["open"]).abs().iloc[-22:-2].mean()
    if avg_body <= 0 and not force:
        return None
    body_ratio = body / avg_body if avg_body > 0 else 0

    prev_top = max(prev.e6, prev.e12, prev.e20)
    fresh = prev.close <= prev_top * 1.02

    sq = df.iloc[-(SQUEEZE_BARS + 1):-1]
    spread = (sq[["e6", "e12", "e20"]].max(axis=1) - sq[["e6", "e12", "e20"]].min(axis=1)) / sq["close"] * 100
    avg_spread = float(spread.mean())

    hist = df.iloc[-TREND_LOOKBACK:-1]
    high_val = hist["high"].max()
    base_low = df.iloc[-(SQUEEZE_BARS + 10):-1]["low"].min()
    drop_pct = (high_val - base_low) / high_val * 100 if high_val > 0 else 0
    falling = df["e20"].iloc[-SQUEEZE_BARS - 2] < df["e20"].iloc[-SQUEEZE_BARS - 30]

    avg_vol = df["vol"].iloc[-22:-2].mean()
    vol_x = last.vol / avg_vol if avg_vol > 0 else 0
    rng = last.high - last.low
    close_pos = (last.close - last.low) / rng if rng > 0 else 1.0

    grade_a = (green_above and body_ratio >= A_BODY_X and body_pct >= A_BODY_PCT and fresh and falling
               and avg_spread <= A_SQUEEZE and drop_pct >= A_DROP_PCT
               and vol_x >= A_VOL_X and close_pos >= A_CLOSE_POS)
    grade_b = (green_above and body_ratio >= B_BODY_X and body_pct >= B_BODY_PCT and fresh and falling
               and avg_spread <= B_SQUEEZE and drop_pct >= B_DROP_PCT)
    grade = "A" if grade_a else ("B" if grade_b else "C")

    score = (min(body_ratio, 6) * 10 + min(drop_pct, 80) / 4
             + max(0, 12 - avg_spread) * 4 + min(vol_x, 5) * 3
             + close_pos * 5 + (10 if fresh else 0) + (5 if falling else 0))

    return {
        "symbol": symbol, "grade": grade, "score": round(float(score), 1),
        "signal_close": float(last.close), "signal_ts": int(last.ts),
        "live_price": float(full.iloc[-1].close),
        "body_pct": round(float(body_pct), 2), "body_x": round(float(body_ratio), 1),
        "vol_x": round(float(vol_x), 1), "drop_pct": round(float(drop_pct), 1),
        "squeeze_pct": round(avg_spread, 2), "full": full,
    }


# ------------------------- CHART -------------------------
def draw_chart(res):
    df = add_emas(res["full"].copy()).iloc[-90:].reset_index(drop=True)
    now = time.time()
    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=110)

    for i, r in df.iterrows():
        live = r["ts"] + INTERVAL_SEC > now
        col = "#16a34a" if r["close"] >= r["open"] else "#ef4444"
        a = 0.55 if live else 1.0
        ax.plot([i, i], [r["low"], r["high"]], color=col, lw=1, alpha=a)
        ax.add_patch(Rectangle((i - 0.35, min(r["open"], r["close"])), 0.7,
                               max(abs(r["close"] - r["open"]), 1e-12),
                               color=col, alpha=a))

    ax.plot(df["e6"],  color="#e879f9", lw=1.4, label="EMA6")
    ax.plot(df["e12"], color="#f59e0b", lw=1.4, label="EMA12")
    ax.plot(df["e20"], color="#6366f1", lw=1.4, label="EMA20")

    idx = df.index[df["ts"] == res["signal_ts"]]
    if len(idx):
        ax.axvspan(idx[0] - 0.5, idx[0] + 0.5, color="#facc15", alpha=0.18, label="Signal candle")

    ticks = list(range(0, len(df), 15))
    ax.set_xticks(ticks)
    ax.set_xticklabels([df["time"].iloc[t].strftime("%m-%d %H:%M") for t in ticks], fontsize=8)
    ax.axhline(res["live_price"], color="#94a3b8", lw=0.8, ls="--")
    ax.text(len(df) - 1, res["live_price"], f" {res['live_price']:.6g}", va="bottom",
            ha="right", fontsize=9, color="#475569")

    ax.set_title(f"[{res['grade']}] {res['symbol']} | {INTERVAL_NAME} | body {res['body_pct']}% "
                 f"({res['body_x']}x) vol {res['vol_x']}x | drop {res['drop_pct']}% | "
                 f"squeeze {res['squeeze_pct']}%", fontsize=10)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    return fig


# ------------------------- TELEGRAM -------------------------
def send_photo(caption, fig):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram secrets missing - skipping send")
        return False
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    data = buf.getvalue()
    for _ in range(3):
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                              data={"chat_id": chat, "caption": caption[:1000]},
                              files={"photo": ("chart.png", data)}, timeout=40)
            if r.ok:
                return True
            print("Telegram error:", r.status_code, r.text[:200])
        except Exception as e:
            print("Telegram exception:", e)
        time.sleep(3)
    return False


def make_caption(res):
    chg = (res["live_price"] / res["signal_close"] - 1) * 100 if res["signal_close"] else 0
    closed_at = pd.to_datetime(res["signal_ts"] + INTERVAL_SEC, unit="s").strftime("%Y-%m-%d %H:%M")
    return (f"🚀 Grade {res['grade']} | {res['symbol']} ({INTERVAL_NAME})\n"
            f"Signal close: {res['signal_close']:.6g}  (closed {closed_at} UTC)\n"
            f"Live price: {res['live_price']:.6g} ({chg:+.2f}%)\n"
            f"Body: {res['body_pct']}% ({res['body_x']}x avg)\n"
            f"Volume: {res['vol_x']}x avg\n"
            f"Prior drop: {res['drop_pct']}%\n"
            f"EMA squeeze: {res['squeeze_pct']}%\n"
            f"Score: {res['score']}")


# ------------------------- STATE -------------------------
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    cutoff = time.time() - 7 * 86400
    state = {k: v for k, v in state.items() if v.get("alert_ts", 0) > cutoff}
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)


# ------------------------- MAIN -------------------------
def main():
    debug = (os.getenv("DEBUG_SYMBOL") or "").strip().upper()
    if debug:
        sym = debug if "_" in debug else debug + "_USDT"
        res = analyse(sym, force=True)
        if not res:
            print(f"No data for {sym}")
            return
        print({k: v for k, v in res.items() if k != "full"})
        fig = draw_chart(res)
        ok = send_photo("🧪 TEST\n" + make_caption(res), fig)
        print("Test chart sent" if ok else "Test chart NOT sent")
        return

    symbols = get_symbols()
    total = len(symbols)
    if MIN_24H_VOL_USDT:
        vols = get_volumes()
        symbols = [s for s in symbols if vols.get(s, 0) >= MIN_24H_VOL_USDT]
    print(f"Scanning {len(symbols)} of {total} MEXC perpetual pairs on {INTERVAL_NAME}...")

    candidates = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = [ex.submit(analyse, s) for s in symbols]
        for n, f in enumerate(as_completed(futures), 1):
            try:
                r = f.result()
                if r:
                    candidates.append(r)
            except Exception:
                pass
            if n % 200 == 0:
                print(f"  {n}/{len(symbols)} done")

    counts = {g: sum(c["grade"] == g for c in candidates) for g in "ABC"}
    print(f"Results -> A: {counts['A']} | B: {counts['B']} | C: {counts['C']} "
          f"| alerting on: {','.join(ALERT_GRADES)}")

    state = load_state()
    to_send = []
    for c in candidates:
        if c["grade"] not in ALERT_GRADES:
            continue
        prev = state.get(c["symbol"])
        # once per 24h per pair, counted by signal candle (0 diff = same candle)
        if prev and c["signal_ts"] - int(prev.get("signal_ts", 0)) < COOLDOWN_HOURS * 3600:
            continue
        to_send.append(c)

    to_send.sort(key=lambda x: (x["grade"], -x["score"]))
    print(f"{len(to_send)} new alerts")

    for c in to_send[:MAX_ALERTS]:
        fig = draw_chart(c)
        ok = send_photo(make_caption(c), fig)
        plt.close(fig)
        if ok:
            state[c["symbol"]] = {"signal_ts": c["signal_ts"], "alert_ts": int(time.time()),
                                  "grade": c["grade"]}
            print(f"  sent {c['symbol']} [{c['grade']}]")
        time.sleep(1.2)

    save_state(state)


if __name__ == "__main__":
    main()
