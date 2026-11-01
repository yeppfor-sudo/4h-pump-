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
TIMEFRAMES = ['5m','15m']  # LIVE top gainers >15% in 5m 15m

BLOCK_ALL = {'BTC','ETH','SOL','BNB','TRX','XRP','ADA','DOGE','AVAX','DOT','LINK','LTC','BCH','XLM','ETC','HBAR','APT','NEAR','UNI','FIL','ARB','OP','ATOM','MATIC','POL','TON','SHIB','PEPE','CRO','LEO','OKB','BGB','SUI','LDO','RNDR','TAO','FET','WIF','ENA','JUP','SEI','TIA','ONDO','W','PYTH','STRK','JTO','ENS'}

def is_valid(sym):
    if not sym.endswith('USDT:USDT'): return False
    base=sym.split('/')[0].upper()
    if base in BLOCK_ALL: return False
    if len(base)<2 or len(base)>8: return False
    if any(c.isdigit() for c in base): return False
    if not base.isalpha(): return False
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
    # Live EMA bearish = early top signal (LSK fix)
    if not (df['ema12'].iloc[-1] < df['ema20'].iloc[-1] or df['ema12'].iloc[-2] < df['ema20'].iloc[-2]):
        return None

    upper=lower=None; events=[]
    for i in range(FRACTAL_LEN, len(df)-1):
        if is_pivot_high(df,i,FRACTAL_LEN): upper=float(df['h'].iloc[i])
        if is_pivot_low(df,i,FRACTAL_LEN): lower=float(df['l'].iloc[i])
        if upper is None or lower is None: continue
        c=float(df['c'].iloc[i]); pc=float(df['c'].iloc[i-1])
        if c < lower and pc >= lower: # break of last low = bear CHoCH
            lb=float(df['l'].iloc[i])
            events.append({'bar':i,'price':c,'upper':upper,'lower':lower,'rangeTop':upper,'rangeBottom':lb,'fib_top':upper-(upper-lb)*0.382,'fib_bot':upper-(upper-lb)*0.618,'ema12':float(df['ema12'].iloc[-1]),'ema20':float(df['ema20'].iloc[-1])})
    
    if not events: return None
    if events[-1]['bar'] < len(df)-25: return None # allow 25 bars old (not 6)
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
print(f"Scan LIVE TOP40 >15% | 5m 15m BEAR CHoCH + EMA12/20 | {now.strftime('%H:%M PKT')}", flush=True)

ex=ccxt.mexc({'enableRateLimit':True,'options':{'defaultType':'swap'}})
ex.load_markets()
tickers = ex.fetch_tickers()

gainers=[]
for sym,t in tickers.items():
    if not is_valid(sym): continue
    try:
        ch = t.get('percentage')
        if ch is None: ch = float(t.get('info',{}).get('riseFallRate',0))*100
        if ch < 15: continue # LIVE >15%
        if (t.get('quoteVolume',0) or 0) < 50000: continue
        gainers.append((sym,float(ch)))
    except: continue

gainers.sort(key=lambda x:x[1],reverse=True)
top=gainers[:TOP_GAINERS]
print(f"TOP {TOP_GAINERS} >15%: {[(s.split('/')[0], f'{c:.1f}%') for s,c in top]}", flush=True)

found=0
for sym,gain in top:
    coin = sym.split('/')[0].upper()
    if coin in hist and time.time()-hist[coin] < COOLDOWN*3600: continue
    for tf in TIMEFRAMES:
        try:
            print(f"Checking {coin} {tf} +{gain:.1f}%", flush=True)
            ohlcv=ex.fetch_ohlcv(sym,tf,limit=300)
            df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            sig=detect_bear_choch(df)
            if not sig: continue
            chart,live=draw(df,sym,sig,'MEXC',tf,gain)
            cap=f"🔴 *BEAR CHoCH {tf}* - TOP40 LIVE >15%\n*Pair:* `{sym}`\n*LIVE:* `+{gain:.2f}%`\n*EMA:* 12 `{sig['ema12']:.6f}` < 20 `{sig['ema20']:.6f}`\n*Break:* `{sig['lower']:.6f}`\n*Short:* `{sig['fib_bot']:.6f}` - `{sig['fib_top']:.6f}`\n*Live:* `{live:.6f}`"
            send_photo(chart,cap)
            hist[coin]=time.time(); save_hist(hist)
            found+=1; break
        except Exception as e:
            print(f"err {coin} {tf} {e}", flush=True)

print(f"Done. Found {found} | 5m 15m LIVE >15% BEAR CHoCH", flush=True)
