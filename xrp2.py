import streamlit as st
import pandas as pd
import requests
import ta
import plotly.graph_objects as go
from streamlit_autorefresh import st_autorefresh

# Auto-refresh every 30 seconds
st_autorefresh(interval=30 * 1000, key="refresh")

# ──────────────────────────────
# Helper: Normalize symbol
# ──────────────────────────────
def clean_symbol(raw: str) -> str:
    s = raw.strip().upper()
    for cut in ("USDT", "/"):
        if cut in s:
            s = s.split(cut)[0]
    return s or "XRP"

# ──────────────────────────────
# Helper: Binance API (readonly)
# ──────────────────────────────
BINANCE_READONLY = "https://data-api.binance.vision"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def call_binance(endpoint: str, params: dict):
    r = requests.get(f"{BINANCE_READONLY}{endpoint}", params=params, headers=HEADERS, timeout=10)
    if r.status_code == 200:
        return r.json()
    st.warning(f"Binance response {r.status_code}: {r.text[:120]}…")
    return None

# ──────────────────────────────
# UI
# ──────────────────────────────
raw = st.text_input("Enter coin symbol (e.g. xrp, btc, eth)", "xrp")
coin = clean_symbol(raw)
PAIR = f"{coin}USDT"
st.caption(f"Fetching data for **{PAIR}**")

# ──────────────────────────────
# Price Candles (1-minute interval)
# ──────────────────────────────
def get_klines(pair: str):
    data = call_binance("/api/v3/klines", {"symbol": pair, "interval": "1m", "limit": 90})
    if not isinstance(data, list):
        return pd.DataFrame()
    cols = ["Time", "Open", "High", "Low", "Close", "Volume", "CloseTime", "QuoteAssetVolume",
            "Trades", "TakerBaseVol", "TakerQuoteVol", "Ignore"]
    df = pd.DataFrame(data, columns=cols)
    df[["Open", "High", "Low", "Close", "Volume"]] = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    df["Time"] = pd.to_datetime(df["Time"], unit="ms")
    df.set_index("Time", inplace=True)
    return df

df = get_klines(PAIR)
if df.empty:
    st.error("❌ Binance returned no rows. Try again later.")
    st.stop()

# ──────────────────────────────
# Live Price (Real-time)
# ──────────────────────────────
price_placeholder = st.empty()
try:
    r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={PAIR}", timeout=10)
    r.raise_for_status()
    last = float(r.json()["price"])
except:
    last = df["Close"].iloc[-1]
    st.warning("⚠️ Live price failed, showing candle close.")

price_placeholder.metric(PAIR, f"${last:,.4f}")

# ──────────────────────────────
# Technical Indicators
# ──────────────────────────────
df["SMA20"] = ta.trend.sma_indicator(df["Close"], 20)
df["RSI"] = ta.momentum.rsi(df["Close"], 14)
macd_line = ta.trend.macd(df["Close"])
macd_signal = ta.trend.macd_signal(df["Close"])
df["MACD_Hist"] = macd_line - macd_signal

signals = [
    "RSI: BUY" if df["RSI"].iloc[-1] < 30 else "RSI: SELL" if df["RSI"].iloc[-1] > 70 else "RSI: HOLD",
    "SMA: BUY" if last > df["SMA20"].iloc[-1] else "SMA: SELL",
    "MACD: BUY" if df["MACD_Hist"].iloc[-1] > 0 else "MACD: SELL",
]
st.subheader("Signals")
st.write(" · ".join(signals))

# ──────────────────────────────
# Fibonacci
# ──────────────────────────────
sub = df[-30:]
hi, lo = sub["High"].max(), sub["Low"].min()
diff = hi - lo
fib = {
    "0%": lo, "23.6%": hi - diff * 0.236, "38.2%": hi - diff * 0.382,
    "50%": hi - diff * 0.5, "61.8%": hi - diff * 0.618,
    "78.6%": hi - diff * 0.786, "100%": hi
}
st.subheader("Fib levels")
st.table(pd.DataFrame(fib.items(), columns=["Level", "Price"]))

# ──────────────────────────────
# Order Book
# ──────────────────────────────
ob = call_binance("/api/v3/depth", {"symbol": PAIR, "limit": 1000}) or {}
bids = [(float(p), float(q), float(p) * float(q)) for p, q in ob.get("bids", [])]
asks = [(float(p), float(q), float(p) * float(q)) for p, q in ob.get("asks", [])]
px = last
top_b = sorted([x for x in bids if x[0] < px], key=lambda z: z[2], reverse=True)[:10]
top_a = sorted([x for x in asks if x[0] > px], key=lambda z: z[2], reverse=True)[:10]

st.subheader("Top 10 buy walls")
for p, _, v in top_b:
    st.write(f"🟢 ${p:,.2f} – {v:,.0f} USD")

st.subheader("Top 10 sell walls")
for p, _, v in top_a:
    st.write(f"🔴 ${p:,.2f} – {v:,.0f} USD")

buy_liq = sum(v for *_, v in top_b)
sell_liq = sum(v for *_, v in top_a)

st.subheader("Liquidity pressure")
if buy_liq > sell_liq * 1.1:
    st.success(f"More buying (${buy_liq:,.0f} vs {sell_liq:,.0f})")
elif sell_liq > buy_liq * 1.1:
    st.error(f"More selling (${sell_liq:,.0f} vs {buy_liq:,.0f})")
else:
    st.info(f"Balanced (${buy_liq:,.0f} vs {sell_liq:,.0f})")

# ──────────────────────────────
# Liquidity Wall Path
# ──────────────────────────────
liq_path = [(df.index[-1], px, "Current")]
b_or_s = True
bidx, aidx = 0, 0
for i in range(1, 11):
    dt = df.index[-1] + pd.Timedelta(minutes=i * 5)
    if b_or_s and bidx < len(top_b):
        price = top_b[bidx][0]
        label = f"Buy @{price:.2f}"
        liq_path.append((dt, price, label))
        bidx += 1
    elif not b_or_s and aidx < len(top_a):
        price = top_a[aidx][0]
        label = f"Sell @{price:.2f}"
        liq_path.append((dt, price, label))
        aidx += 1
    b_or_s = not b_or_s

# ──────────────────────────────
# Final Chart
# ──────────────────────────────
st.subheader("Candlestick Chart + SMA20 + Liquidity Wall Path")
fig = go.Figure()

fig.add_trace(go.Candlestick(
    x=df.index,
    open=df["Open"], high=df["High"],
    low=df["Low"], close=df["Close"],
    name="Candles"
))

fig.add_trace(go.Scatter(
    x=df.index,
    y=df["SMA20"],
    mode="lines",
    name="SMA20",
    line=dict(color="blue")
))

x, y, labels = zip(*liq_path)
fig.add_trace(go.Scatter(
    x=x, y=y,
    mode="lines+markers+text",
    name="Liquidity Path",
    text=labels,
    textposition="top center",
    line=dict(color="orange", dash="dot")
))

fig.update_layout(xaxis_rangeslider_visible=False, height=700)
st.plotly_chart(fig, use_container_width=True)

# ──────────────────────────────
# RSI + MACD Display
# ──────────────────────────────
st.subheader("RSI (14)")
st.line_chart(df["RSI"])

st.subheader("MACD Histogram")
st.bar_chart(df["MACD_Hist"])
