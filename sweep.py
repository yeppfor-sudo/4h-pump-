import numpy as np
import pandas as pd
from config import *

# True  = confirmation candle must not break the sweep extreme and must close
#         back on the right side of the swept level
# False = alert after any one more closed candle
CONFIRM_HOLD = True


def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def _atr(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def _flip(df):
    f = df.copy()
    f["open"] = -df["open"]
    f["close"] = -df["close"]
    f["high"] = -df["low"]
    f["low"] = -df["high"]
    return f


def _pivot_lows(lo, k, start, s):
    out = []
    for i in range(max(start, k), s - k):
        if lo[i] < lo[i - k:i].min() and lo[i] <= lo[i + 1:i + k + 1].min():
            out.append(i)
    return out


def _long(df, tf, live):
    """Sell-side liquidity sweep -> long. Shorts reuse this on a flipped frame.
    The sweep candle is the LAST candle of df."""
    L, k = LOOKBACK[tf], PIVOT_K
    s = len(df) - 1
    if s < L + 5:
        return None
    lo, hi = df["low"].values, df["high"].values
    op, cl = df["open"].values, df["close"].values
    vol = df["vol"].values
    at = _atr(df).values[s]
    if not np.isfinite(at) or at <= 0:
        return None

    rng = hi[s] - lo[s]
    if rng < MIN_RANGE_ATR * at:
        return None
    wick = (min(op[s], cl[s]) - lo[s]) / rng
    cpos = (cl[s] - lo[s]) / rng
    if wick < MIN_WICK or cpos < MIN_CLOSE_POS:
        return None

    st = max(s - L, k)
    cands = []
    for i in _pivot_lows(lo, k, st, s):
        if i + 1 < s and lo[i + 1:s].min() <= lo[i]:
            continue  # already swept earlier
        cands.append((lo[i], i))
    rl = st + int(np.argmin(lo[st:s]))
    if not any(i == rl for _, i in cands):
        cands.append((lo[rl], rl))

    tol = EQL_TOL_ATR * at
    swept = []
    for lvl, i in cands:
        if lo[s] < lvl - 0.05 * at and cl[s] > lvl:
            touches = sum(1 for l2, _ in cands if abs(l2 - lvl) <= tol)
            swept.append((touches, -lvl, lvl, i))
    if not swept:
        return None
    touches, _, lvl, li = max(swept)

    depth = (lvl - lo[s]) / at
    if depth < MIN_DEPTH_ATR or depth > MAX_DEPTH_ATR:
        return None

    vm = vol[max(0, s - 20):s].mean()
    if vm <= 0:
        return None
    vr = vol[s] / vm

    # ---- score (0-100) ----
    sc = 8 + 17 * np.clip((wick - 0.40) / 0.40, 0, 1)             # wick 25
    if depth < 0.3:
        sc += 15 * (depth - 0.1) / 0.2                              # depth 15
    elif depth <= 1.5:
        sc += 15
    else:
        sc += 15 - 10 * (depth - 1.5) / 1.5
    sc += 5 + 10 * np.clip((cpos - 0.5) / 0.5, 0, 1)                # reclaim 15
    sc += min(15, 5 + 4 * (touches - 1) + (3 if s - li >= 5 else 0))  # level 15
    sc += 15 * np.clip((vr - 0.8) / 1.2, 0, 1)                      # volume 15
    e20 = _ema(df["close"], 20).values
    if cl[s - 1] < e20[s - 1]:
        sc += 5                                                     # downtrend
    hh = hi[st:s].max()
    if (hh - lvl) / at >= 5:
        sc += 5                                                     # extended move
    r = _rsi(df["close"]).values[s]
    if np.isfinite(r) and r <= 40:
        sc += 5                                                     # oversold
    sc = float(round(min(sc, 100), 1))

    entry = cl[s]
    sl = lo[s] - SL_BUFFER_ATR * at
    risk = entry - sl
    if risk <= 0 or risk > MAX_RISK_ATR * at:
        return None
    tp1, tp2 = entry + 1.5 * risk, entry + 3 * risk
    tp3 = hh if hh > tp2 else entry + 5 * risk

    notes = []
    if touches >= 2:
        notes.append(f"Equal levels x{touches}")
    notes.append(f"Wick {wick * 100:.0f}%")
    notes.append(f"Volume {vr:.1f}x")

    return dict(level=lvl, extreme=lo[s], entry=entry, sl=sl,
                tp1=tp1, tp2=tp2, tp3=tp3, score=sc,
                grade="A" if sc >= 70 else "B" if sc >= 55 else "C",
                wick=wick, depth=depth, vr=vr, touches=touches,
                rsi=float(r) if np.isfinite(r) else 0.0, notes=notes,
                atr=float(at), hh=float(hh))


def _confirm(r, cf, live):
    """Apply the confirmation candle `cf` (same frame as r, long logic)."""
    if CONFIRM_HOLD:
        if cf["low"] <= r["extreme"] or cf["close"] <= r["level"]:
            return None
    entry = float(cf["close"])
    sl = r["sl"]
    risk = entry - sl
    if risk <= 0 or risk > MAX_RISK_ATR * r["atr"]:
        return None
    tp1, tp2 = entry + 1.5 * risk, entry + 3 * risk
    tp3 = r["hh"] if r["hh"] > tp2 else entry + 5 * risk
    # stale filter: already stopped out or already ran to TP1
    if live <= sl or live >= tp1:
        return None
    r.update(entry=entry, tp1=tp1, tp2=tp2, tp3=tp3)
    return r


def detect(sym, tf, closed, full):
    """Sweep candle = second-last closed candle,
    confirmation candle = last closed candle."""
    if len(closed) < LOOKBACK[tf] + 16:
        return []
    live = float(full["close"].iloc[-1])
    out = []
    for side in ("long", "short"):
        if side == "long":
            frame, sg, lv = closed, 1, live
        else:
            frame, sg, lv = _flip(closed), -1, -live
        sweep = frame.iloc[:-1].reset_index(drop=True)
        cf = frame.iloc[-1]
        r = _long(sweep, tf, float(sweep["close"].iloc[-1]))
        if not r:
            continue
        r = _confirm(r, cf, lv)
        if not r:
            continue
        for key in ("level", "extreme", "entry", "sl", "tp1", "tp2", "tp3"):
            r[key] = sg * r[key]
        r.pop("hh", None)
        if side == "short":
            r["rsi"] = 100 - r["rsi"]
        r.update(side=side, symbol=sym, tf=tf,
                 pos=len(closed) - 2, conf_pos=len(closed) - 1,
                 start=int(closed["start"].iloc[-2]),
                 conf_start=int(closed["start"].iloc[-1]),
                 end=int(closed["end"].iloc[-1]))
        out.append(r)
    return out
