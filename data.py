import time
import requests
import pandas as pd
from config import *

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"


def _get(url, params=None, tries=4):
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=20)
            if r.status_code == 200:
                j = r.json()
                if j.get("success", True):
                    return j
            elif r.status_code == 429:
                time.sleep(2 * (i + 1))
        except Exception:
            pass
        time.sleep(1 + i)
    return None


def list_symbols():
    j = _get(BASE + "/api/v1/contract/detail")
    out, skipped = [], []
    for c in (j or {}).get("data", []) or []:
        sym = c.get("symbol", "")
        if c.get("quoteCoin") != "USDT" or c.get("state") != 0:
            continue
        base = str(c.get("baseCoin", "")).upper()
        plates = " ".join(str(x) for x in (c.get("conceptPlate") or [])).lower()
        if base in EXCLUDE_BASE or any(w in plates for w in EXCLUDE_WORDS):
            skipped.append(sym)
            continue
        out.append(sym)
    return out, skipped


def fetch_daily(sym):
    end = int(time.time())
    start = end - HISTORY_DAYS * 86400
    j = _get(f"{BASE}/api/v1/contract/kline/{sym}",
             {"interval": "Day1", "start": start, "end": end})
    if not j:
        return None
    d = j.get("data") or {}
    if not d.get("time"):
        return None
    df = pd.DataFrame({
        "ts": d["time"], "open": d["open"], "high": d["high"],
        "low": d["low"], "close": d["close"], "vol": d["vol"],
    }).astype(float)
    return df.sort_values("ts").reset_index(drop=True)


def resample(df, n):
    """Build n-day candles from daily data (7d = Monday-anchored weeks).
    Returns (closed_candles, all_candles_including_live)."""
    now = time.time()
    off = int(df["ts"].iloc[0]) % 86400
    shift = 0 if off == 0 else 86400 - off
    day = ((df["ts"] + shift) // 86400).astype(int) - 4  # 1970-01-05 = Monday
    key = day // n
    g = (df.assign(key=key).groupby("key", sort=True)
         .agg(open=("open", "first"), high=("high", "max"),
              low=("low", "min"), close=("close", "last"),
              vol=("vol", "sum"), cnt=("ts", "count"))
         .reset_index())
    g["start"] = (g["key"] * n + 4) * 86400 - shift
    g["end"] = g["start"] + n * 86400
    if len(g) and g.loc[0, "cnt"] < n:
        g = g.iloc[1:]
    g = g.reset_index(drop=True)
    closed = g[g["end"] <= now].reset_index(drop=True)
    return closed, g
