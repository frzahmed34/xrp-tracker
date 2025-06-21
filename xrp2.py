import streamlit as st
import pandas as pd
import requests
import ta
from datetime import datetime

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def clean_symbol(raw: str) -> str:
    """
    Normalise whatever the user types into a pure coin symbol.
    e.g. 'xrpUSDT '  -> 'XRP'
         ' btc/usdt' -> 'BTC'
         'eth'       -> 'ETH'
    """
    s = raw.strip().upper()
    # strip anything after USDT (or the separator '/')
    for cut in ("USDT", "/"):
        if cut in s:
            s = s.split(cut)[0]
    return s or "XRP"      # fallback to XRP if empty


def full_pair(sym: str) -> str:
    """Return full Binance trading pair, e.g. 'XRP' -> 'XRPUSDT' """
    return f"{sym}USDT"


def call_binance(endpoint: str, params: dict) -> dict | list:
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(
        f"https://api.binance.com{endpoint}",
        params=params,
        headers=headers,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()

# ─────────────────────────────────────────────────────────────
# Streamlit UI
# ─────────────────────────────────────────────────────────────
raw_input = st.text_input("Enter coin symbol (e.g. xrp, btc, eth)", "xrp")
coin      = clean_symbol(raw_input)
PAIR      = full_pair(coin)
st.caption(f"Fetching data for **{PAIR}**")

@st.cache_data(show_spinner=False)
def get_klines(pair: str) -> pd.DataFrame:
    data = call_binance(
        "/api/v3/klines",
        {"symbol": pair, "interval": "1d", "limit": 90},
    )
    if not isinstance(data, list) or len(data) == 0:
        return pd.DataFrame()

    cols = [
        "Time","Open","High","Low","Close","Volume",
        "CloseTime","QuoteAssetVolume","Trades",
        "TakerBaseVol","TakerQuoteVol","Ignore",
    ]
    df = pd.DataFrame(data, columns=cols)
    df[["Open","High","Low","Close","Volume"]] = df[["Open","High","Low","Close","Volume"]].astype(float)
    df["Time"] = pd.to_datetime(df["Time"], unit="ms")
    df.set_index("Time", inplace=True)
    return df


df = get_klines(PAIR)

if df.empty:
    st.error("No data returned for that symbol – double-check spelling or try again in a minute.")
    st.stop()

# ─────────────────────────────────────────────────────────────
# Technical indicators
# ─────────────────────────────────────────────────────────────
df["SMA20"]    = ta.trend.sma_indicator(df["Close"], window=20)
df["RSI"]      = ta.momentum.rsi(df["Close"], window=14)
macd_line      = ta.trend.macd(df["Close"])
macd_signal    = ta.trend.macd_signal(df["Close"])
df["MACD_Hist"] = macd_line - macd_signal

last_price = df["Close"].iloc[-1]
st.metric(f"{PAIR} price", f"${last_price:,.4f}")

signals = [
    "RSI: BUY"  if df["RSI"].iloc[-1] < 30 else
    "RSI: SELL" if df["RSI"].iloc[-1] > 70 else
    "RSI: HOLD",
    "SMA: BUY"  if last_price > df["SMA20"].iloc[-1] else "SMA: SELL",
    "MACD: BUY" if df["MACD_Hist"].iloc[-1] > 0   else "MACD: SELL",
]

st.subheader("Technical signals")
st.write(" · ".join(signals))

# ─────────────────────────────────────────────────────────────
# Fibonacci levels
# ─────────────────────────────────────────────────────────────
def fib_levels(d: pd.DataFrame, lookback: int = 30) -> dict:
    sub = d[-lookback:]
    hi, lo = sub["High"].max(), sub["Low"].min()
    diff   = hi - lo
    return {
        "0.0 %": lo,
        "23.6 %": hi - diff * 0.236,
        "38.2 %": hi - diff * 0.382,
        "50.0 %": hi - diff * 0.500,
        "61.8 %": hi - diff * 0.618,
        "78.6 %": hi - diff * 0.786,
        "100 %":  hi,
    }

fib = fib_levels(df)
st.subheader("Fibonacci (last 30 d)")
st.table(pd.DataFrame(fib.items(), columns=["Level", "Price"]))

# ─────────────────────────────────────────────────────────────
# Order-book liquidity
# ─────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def order_book(pair: str):
    data = call_binance("/api/v3/depth", {"symbol": pair, "limit": 1000})
    return data.get("bids", []), data.get("asks", [])

bids, asks = order_book(PAIR)
px  = last_price
b   = [(float(p), float(q), float(p) * float(q)) for p, q in bids]
a   = [(float(p), float(q), float(p) * float(q)) for p, q in asks]
top_b = sorted([x for x in b if x[0] < px], key=lambda z: z[2], reverse=True)[:10]
top_a = sorted([x for x in a if x[0] > px], key=lambda z: z[2], reverse=True)[:10]

st.subheader("Top 10 buy walls")
for p, q, v in top_b:
    st.write(f"🟢 ${p:,.2f} — {v:,.0f} USD")

st.subheader("Top 10 sell walls")
for p, q, v in top_a:
    st.write(f"🔴 ${p:,.2f} — {v:,.0f} USD")

buy_liq  = sum(v for _, _, v in top_b)
sell_liq = sum(v for _, _, v in top_a)

st.subheader("Liquidity pressure")
if buy_liq > sell_liq * 1.1:
    st.success(f"More buying pressure (${buy_liq:,.0f} vs ${sell_liq:,.0f})")
elif sell_liq > buy_liq * 1.1:
    st.error(f"More selling pressure (${sell_liq:,.0f} vs ${buy_liq:,.0f})")
else:
    st.info(f"Balanced (${buy_liq:,.0f} vs ${sell_liq:,.0f})")
