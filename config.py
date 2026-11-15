import os

BASE = "https://contract.mexc.com"

# timeframe -> number of daily candles per candle
TIMEFRAMES = {"1d": 1, "2d": 2, "3d": 3, "5d": 5, "7d": 7}
# how many closed candles back to look for liquidity levels
LOOKBACK = {"1d": 30, "2d": 25, "3d": 20, "5d": 16, "7d": 14}

PIVOT_K = 2
HISTORY_DAYS = 900

# sweep candle gates
MIN_WICK = 0.40          # sweep wick must be >= 40% of candle range
MIN_CLOSE_POS = 0.50     # must close in the upper half (lower half for shorts)
MIN_RANGE_ATR = 0.8      # candle range >= 0.8 ATR
MIN_DEPTH_ATR = 0.10     # sweep depth beyond level (in ATR)
MAX_DEPTH_ATR = 3.0      # deeper than this = breakdown, not sweep
EQL_TOL_ATR = 0.25       # tolerance for equal highs/lows
SL_BUFFER_ATR = 0.10
MAX_RISK_ATR = 4.0

MIN_SCORE = float(os.getenv("MIN_SCORE", "70"))      # Grade A
MAX_AGE_HOURS = float(os.getenv("MAX_AGE_HOURS", "30"))
TOP_N = int(os.getenv("TOP_N", "25"))
WORKERS = int(os.getenv("WORKERS", "4"))
RATE_SLEEP = float(os.getenv("RATE_SLEEP", "0.25"))
TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
WATERMARK = "RANJHA"

# crypto only: skip stock / ETF / metal contracts
EXCLUDE_WORDS = ("stock", "etf", "metal", "forex", "commodity")
EXCLUDE_BASE = {
    "XAU", "XAG", "XPT", "XPD", "TSLA", "NVDA", "AAPL", "MSFT", "GOOGL",
    "AMZN", "COIN", "MSTR", "HOOD", "CRCL", "CRWV", "PLTR", "SPY", "QQQ",
    "GLD", "SLV", "IWM", "NFLX", "AMD", "INTC", "BABA", "TSM", "ORCL",
    "UBER", "DIS", "NKE", "PYPL", "SHOP", "SNOW", "ARM", "AVGO", "LLY",
}


def fmt(p):
    return f"{p:.6g}"
