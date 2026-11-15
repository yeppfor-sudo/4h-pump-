import time
import concurrent.futures as cf
from config import *
from data import list_symbols, fetch_daily, resample
from sweep import detect
from chart import make_chart
from notify import (load_state, save_state, caption, send_photo, send_text)


def cutoff(tf):
    return 40 if TEST_MODE else MIN_SCORE_TF[tf]


def work(sym):
    time.sleep(RATE_SLEEP)
    df = fetch_daily(sym)
    if df is None or len(df) < 60 or df["vol"].tail(20).sum() <= 0:
        return []
    out = []
    for tf, n in TIMEFRAMES.items():
        closed, full = resample(df, n)
        for s in detect(sym, tf, closed, full):
            cut = cutoff(tf)
            if s["score"] >= cut:
                s["cut"] = cut
                s["grade"] = ("A" if s["score"] >= cut
                              else "B" if s["score"] >= cut - 10 else "C")
                s["_full"] = full
                out.append(s)
    return out


def main():
    syms, skipped = list_symbols()
    print(f"Scanning {len(syms)} crypto USDT perps (skipped {len(skipped)} non-crypto)")
    print("Cutoffs:", MIN_SCORE_TF if not TEST_MODE else "TEST MODE (40)")
    results = []
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(work, s): s for s in syms}
        for f in cf.as_completed(futs):
            try:
                results += f.result()
            except Exception as e:
                print("error", futs[f], e)

    now = time.time()
    st = load_state()
    fresh = []
    for s in results:
        s["age_h"] = (now - s["end"]) / 3600
        s["key"] = f"{s['symbol']}|{s['tf']}|{s['side']}|{s['start']}"
        if not TEST_MODE:
            if s["age_h"] > MAX_AGE_HOURS or s["key"] in st:
                continue
        fresh.append(s)
    # rank by how far above its own timeframe cutoff
    fresh.sort(key=lambda x: -(x["score"] - x["cut"]))
    fresh = fresh[: (3 if TEST_MODE else TOP_N)]
    print(f"{len(results)} raw signals, {len(fresh)} to send")

    sent = []
    for s in fresh:
        try:
            img = make_chart(s["_full"], s)
            if send_photo(img, caption(s)):
                sent.append(s)
                if not TEST_MODE:
                    st[s["key"]] = now
            time.sleep(1.3)
        except Exception as e:
            print("send error", s["symbol"], e)

    if not TEST_MODE:
        save_state(st)

    if sent:
        lines = ["<b>Liquidity sweep summary</b>"]
        for s in sent:
            e = "🟢" if s["side"] == "long" else "🔴"
            lines.append(f"{e} {s['symbol']} {s['tf'].upper()} - "
                         f"{s['grade']} ({s['score']})")
        send_text("\n".join(lines))
    elif TEST_MODE:
        send_text(f"Test finished: scanned {len(syms)} pairs, "
                  f"{len(results)} signals found, none sent.")


if __name__ == "__main__":
    main()
