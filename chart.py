import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from config import *


def make_chart(full, sig):
    df = full.copy()
    df.index = pd.to_datetime(df["start"], unit="s")
    c = df["close"]
    emas = {n: c.ewm(span=n, adjust=False).mean() for n in (6, 12, 20)}
    N = 70
    d = (df[["open", "high", "low", "close", "vol"]]
         .rename(columns=str.capitalize).rename(columns={"Vol": "Volume"})
         .tail(N))
    base = len(df) - len(d)
    x = sig["pos"] - base
    xc = sig["conf_pos"] - base
    n = len(d)

    aps = [mpf.make_addplot(emas[m].tail(N), color=col, width=1.0)
           for m, col in ((6, "#f0b90b"), (12, "#a855f7"), (20, "#2563eb"))]
    mc = mpf.make_marketcolors(up="#0ecb81", down="#f6465d", edge="inherit",
                               wick="inherit", volume="inherit")
    style = mpf.make_mpf_style(marketcolors=mc, facecolor="white",
                               figcolor="white", gridcolor="#eceff1",
                               gridstyle="-", y_on_right=True)
    fig, axes = mpf.plot(d, type="candle", style=style, addplot=aps,
                         volume=True, returnfig=True, figsize=(9, 6.5),
                         panel_ratios=(4, 1), datetime_format="%d %b",
                         xrotation=0, tight_layout=True)
    ax = axes[0]

    lo, hi = d["Low"].min(), d["High"].max()
    ymin = min(lo, sig["sl"], sig["tp2"])
    ymax = max(hi, sig["sl"], sig["tp2"])
    pad = (ymax - ymin) * 0.06
    ymin, ymax = ymin - pad, ymax + pad
    ax.set_ylim(ymin, ymax)
    ax.set_xlim(-1, n + 9)

    lines = [("Swept", sig["level"], "#f59e0b"),
             ("Entry", sig["entry"], "#2563eb"),
             ("SL", sig["sl"], "#f6465d"),
             ("TP1", sig["tp1"], "#0ecb81"),
             ("TP2", sig["tp2"], "#0ecb81")]
    if ymin <= sig["tp3"] <= ymax:
        lines.append(("TP3", sig["tp3"], "#0ecb81"))
    for label, price, col in lines:
        x0 = max(x - 12, 0) if label == "Swept" else max(xc - 1, 0)
        x1 = xc + 2 if label == "Swept" else n + 1
        ax.hlines(price, x0, x1, colors=col, linestyles="--", linewidth=1.1)
        ax.text(n + 1.2, price, f"{label} {fmt(price)}", color=col,
                fontsize=8, va="center")

    off = (ymax - ymin) * 0.10
    long_ = sig["side"] == "long"
    ty = sig["extreme"] - off if long_ else sig["extreme"] + off
    ax.annotate("SWEEP", xy=(x, sig["extreme"]), xytext=(x, ty), ha="center",
                color="#f59e0b", fontsize=9, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color="#f59e0b"))

    if 0 <= xc < n:
        cy = d["High"].iloc[xc] if long_ else d["Low"].iloc[xc]
        cty = cy + off if long_ else cy - off
        ax.annotate("CONFIRM", xy=(xc, cy), xytext=(xc, cty), ha="center",
                    color="#2563eb", fontsize=9, fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color="#2563eb"))

    ax.set_title(f"{sig['symbol']}  {sig['tf'].upper()}  |  "
                 f"{sig['side'].upper()} sweep + confirmation  |  "
                 f"Score {sig['score']} (Grade {sig['grade']})", fontsize=11)
    fig.text(0.5, 0.5, WATERMARK, fontsize=70, color="gray", alpha=0.12,
             ha="center", va="center", rotation=30)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
