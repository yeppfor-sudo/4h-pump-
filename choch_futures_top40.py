import os, ccxt, pandas as pd, requests, json, time, pytz
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
PKT = pytz.timezone('Asia/Karachi')
HIST_FILE = "alerts_history.json"
FRACTAL_LEN = 5
COOLDOWN = 24
TOP_GAINERS = 40
TIMEFRAMES = ['5m','15m']
GAIN_THRESHOLD = 7

BLOCK_ALL = {'BTC','ETH','SOL','BNB','TRX','XRP','ADA','DOGE','AVAX','DOT','LINK','LTC','BCH','XLM','ETC','HBAR','APT','NEAR','UNI','FIL','ARB','OP','ATOM','MATIC','POL','TON','SHIB','PEPE','CRO','LEO','OKB','BGB','SUI','LDO','RNDR','TAO','FET','WIF','ENA','JUP','SEI','TIA','ONDO','W','PYTH','STRK','JTO','ENS'}

def is_valid(base):
    b=base.upper().replace('1000','').replace('10000','')
    if b in BLOCK_ALL: return False
    if len(b)<2 or len(b)>12: return False
    # allow only A-Z, block Chinese like 牛来
    if not b.isalpha(): return False
    return True

def send_photo(p,c):
    try:
        with open(p,'rb') as f: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data={"chat_id":CHAT,"caption":c,"parse_mode":"Markdown"}, files={"photo":f}, timeout=30)
    except Exception as e: print(f"photo fail {e}", flush=True)

def load_hist():
    try: return json.load(open(HIST_FILE))
    except: return {}
def save_hist(d): json.dump(d, open(HIST_FILE,'w'))

def is_pivot_high(df,i,l): 
    if i<l or i>=len(df)-l: return False
    return df['h'].iloc[i]==df['h'].iloc[i-l:i+l+1].max()
def is_pivot_low(df,i,l):
    if i<l or i>=len(df)-l: return False
    return df['l'].iloc[i]==df['l'].iloc[i-l:i+l+1].min()

def detect_bear_choch(df):
    if len(df)<80: return None
    df['ema12'] = df['c'].ewm(span=12, adjust=False).mean()
    df['ema20'] = df['c'].ewm(span=20, adjust=False).mean()
    if not (df['ema12'].iloc[-1] < df['ema20'].iloc[-1] or df['ema12'].iloc[-2] < df['ema20'].iloc[-2]):
        return None
    upper=lower=None; events=[]
    for i in range(FRACTAL_LEN, len(df)-1):
        if is_pivot_high(df,i,FRACTAL_LEN): upper=float(df['h'].iloc[i])
        if is_pivot_low(df,i,FRACTAL_LEN): lower=float(df['l'].iloc[i])
        if upper is None or lower is None: continue
        c=float(df['c'].iloc[i]); pc=float(df['c'].iloc[i-1])
        if c < lower and pc >= lower:
            lb=float(df['l'].iloc[i])
            events.append({'bar':i,'price':c,'upper':upper,'lower':lower,'rangeTop':upper,'rangeBottom':lb,'fib_top':upper-(upper-lb)*0.382,'fib_bot':upper-(upper-lb)*0.618,'ema12':float(df['ema12'].iloc[-1]),'ema20':float(df['ema20'].iloc[-1])})
    if not events: return None
    if events[-1]['bar'] < len(df)-25: return None
    return events[-1]

def draw(df,sym,sig,exn,tf,gain):
    fig,ax=plt.subplots(figsize=(14,6),facecolor='black'); ax.set_facecolor('black')
    view=df.tail(80); live=float(view['c'].iloc[-1])
    for i,(_,r) in enumerate(view.iterrows()):
        col='#089981' if r['c']>=r['o'] else '#f23645'
        ax.plot([i,i],[r['l'],r['h']],color=col,lw=1); ax.plot([i,i],[r['o'],r['c']],color=col,lw=4)
    ax.plot(range(len(view)), view['ema12'].tail(80), color='#2962FF', lw=1.2, label='EMA12')
    ax.plot(range(len(view)), view['ema20'].tail(80), color='#FF6D00', lw=1.2, label='EMA20')
    ax.axhline(sig['lower'],color='white',ls='--',lw=1.2,label=f"BREAK {sig['lower']:.6f}")
    ax.axhspan(sig['fib_bot'],sig['fib_top'],color='#f23645',alpha=0.45,label="SELL ZONE")
    ax.axhline(live,color='yellow',lw=1.2,label=f"LIVE {live:.6f}")
    ax.set_title(f"{sym} {exn} {tf} BEAR CHoCH | LIVE +{gain:.1f}%",color='white',fontweight='bold')
    ax.legend(facecolor='black',labelcolor='white',fontsize=7); ax.grid(alpha=0.15); plt.tight_layout()
    p=f"chart_{sym.replace('/','').replace(':','')}_{tf}.png"; plt.savefig(p,dpi=150,facecolor='black'); plt.close(); return p,live

hist=load_hist()
now=datetime.now(PKT)
print(f"Scan LIVE TOP40 >{GAIN_THRESHOLD}% | 5m 15m BEAR CHoCH | {now.strftime('%H:%M PKT')}", flush=True)

# --- FIXED GAINERS FETCH - TRY 3 ENDPOINTS ---
gainers_raw=[]
try:
    # Endpoint 1: contract ticker
    r1 = requests.get("https://contract.mexc.com/api/v1/contract/ticker", timeout=10).json()
    for t in r1.get('data',[]):
        sym=t['symbol']
        if not sym.endswith('_USDT'): continue
        base=sym.replace('_USDT','')
        gainers_raw.append((base, float(t.get('riseFallRate',0))*100, f"{base}/USDT:USDT", "c1"))
    print(f"c1 got {len(gainers_raw)}", flush=True)
except Exception as e: print(f"c1 fail {e}", flush=True)

try:
    # Endpoint 2: spot 24hr ticker (often has ESPORTS, AIOT etc)
    r2 = requests.get("https://api.mexc.com/api/v3/ticker/24hr", timeout=10).json()
    for t in r2:
        sym=t['symbol']
        if not sym.endswith('USDT'): continue
        base=sym.replace('USDT','')
        ch=float(t.get('priceChangePercent',0))*100
        if ch < GAIN_THRESHOLD: continue
        gainers_raw.append((base, ch, f"{base}/USDT:USDT", "s3"))
    print(f"s3 added, total {len(gainers_raw)}", flush=True)
except Exception as e: print(f"s3 fail {e}", flush=True)

# Merge, dedup by base, keep highest gain
merged={}
for base,ch,sym,src in gainers_raw:
    if base not in merged or ch > merged[base][1]:
        merged[base]=(base,ch,sym)

all_sorted=sorted(merged.values(), key=lambda x:x[1], reverse=True)
print(f"RAW TOP 20 BEFORE FILTER: {all_sorted[:20]}", flush=True)

# Now apply is_valid filter
filtered=[]
for base,ch,sym in all_sorted:
    if not is_valid(base): 
        print(f"Filtered out {base} {ch:.1f}% - invalid", flush=True)
        continue
    if ch < GAIN_THRESHOLD: continue
    filtered.append((base,ch,sym))

top=filtered[:TOP_GAINERS]
print(f"FINAL TOP {TOP_GAINERS} >{GAIN_THRESHOLD}% : {top[:15]}", flush=True)

if not top:
    print("No top gainers, abort", flush=True)
    exit()

ex=ccxt.mexc({'enableRateLimit':True,'options':{'defaultType':'swap'}})
ex.load_markets()

found=0
for base,gain,sym in top:
    coin=base.upper()
    if coin in hist and time.time()-hist[coin] < COOLDOWN*3600: continue
    for tf in TIMEFRAMES:
        try:
            print(f"Checking {coin} {tf} +{gain:.1f}%", flush=True)
            ohlcv=ex.fetch_ohlcv(sym,tf,limit=300)
            df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            sig=detect_bear_choch(df)
            if not sig: continue
            chart,live=draw(df,sym,sig,'MEXC',tf,gain)
            cap=f"🔴 *BEAR CHoCH {tf}* TOP40 LIVE >{GAIN_THRESHOLD}%\n*Pair:* `{sym}`\n*LIVE:* `+{gain:.2f}%`\n*EMA:* 12 `{sig['ema12']:.6f}` < 20 `{sig['ema20']:.6f}`\n*Break:* `{sig['lower']:.6f}`\n*Short:* `{sig['fib_bot']:.6f}` - `{sig['fib_top']:.6f}`\n*Live:* `{live:.6f}`"
            send_photo(chart,cap)
            hist[coin]=time.time(); save_hist(hist)
            found+=1; break
        except Exception as e:
            print(f"err {coin} {tf} {e}", flush=True)

print(f"Done. Found {found} | 5m 15m LIVE >{GAIN_THRESHOLD}% BEAR CHoCH", flush=True)
