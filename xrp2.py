import streamlit as st
import pandas as pd
import requests
import ta
import plotly.graph_objects as go

# ────────────────────────────
# Helper: normalize symbol
# ────────────────────────────
def clean_symbol(raw: str) -> str:
    s = raw.strip().upper()
    for cut in ("USDT", "/"):
        if cut in s:
            s = s.split(cut)[0]
    return s or "XRP"

# ────────────────────────────
# Helper: call Binance (mirror)
# ────────────────────────────
BINANCE_READONLY = "https://data-api.binance.vision"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def call_binance(endpoint: str, params: dict):
    r = requests.get(f"{BINANCE_READONLY}{endpoint}", params=params, headers=HEADERS, timeout=10)
    if r.status_code == 200:
        return r.json()
    st.warning(f"Binance response {r.status_code}: {r.text[:120]}…")
    return None

# ────────────────────────────
# UI
# ────────────────────────────
raw = st.text_input("Enter coin symbol (e.g. xrp, btc, eth)", "xrp")
coin = clean_symbol(raw)
PAIR = f"{coin}USDT"
st.caption(f"Fetching data for **{PAIR}**")

# ────────────────────────────
# Price candles
# ────────────────────────────
@st.cache_data(show_spinner=False)
def get_klines(pair: str):
    data = call_binance("/api/v3/klines", {"symbol": pair, "interval": "1d", "limit": 90})
    if not isinstance(data, list):
        return pd.DataFrame()
    cols = ["Time", "Open", "High", "Low", "Close", "Volume", "CloseTime", "QuoteAssetVolume", "Trades", "TakerBaseVol", "TakerQuoteVol", "Ignore"]
    df = pd.DataFrame(data, columns=cols)
    df[["Open", "High", "Low", "Close", "Volume"]] = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    df["Time"] = pd.to_datetime(df["Time"], unit="ms")
    df.set_index("Time", inplace=True)
    return df

df = get_klines(PAIR)
if df.empty:
    st.error("❌ Binance returned no rows. Try again later.")
    st.stop()

# ────────────────────────────
# Technicals
# ────────────────────────────
df["SMA20"] = ta.trend.sma_indicator(df["Close"], 20)
last = df["Close"].iloc[-1]
st.metric(PAIR, f"${last:,.4f}")

# ────────────────────────────
# Order-book data
# ────────────────────────────
ob = call_binance("/api/v3/depth", {"symbol": PAIR, "limit": 1000}) or {}
bids = [(float(p), float(q), float(p) * float(q)) for p, q in ob.get("bids", [])]
asks = [(float(p), float(q), float(p) * float(q)) for p, q in ob.get("asks", [])]
px = last
top_b = sorted([x for x in bids if x[0] < px], key=lambda z: z[2], reverse=True)[:10]
top_a = sorted([x for x in asks if x[0] > px], key=lambda z: z[2], reverse=True)[:10]

# ────────────────────────────
# Liquidity path
# ────────────────────────────
liq_path = [(df.index[-1], px, "Current")]
b_or_s = True
bidx, aidx = 0, 0
for i in range(1, 6):
    dt = df.index[-1] + pd.Timedelta(days=i * 2)  # Space points by 2 days
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

# ────────────────────────────
# Combined chart
# ────────────────────────────
fig = go.Figure()

# Candles
fig.add_trace(go.Candlestick(
    x=df.index, open=df["Open"], high=df["High"],
    low=df["Low"], close=df["Close"], name="Candles"
))

# SMA20
fig.add_trace(go.Scatter(
    x=df.index, y=df["SMA20"], mode="lines",
    name="SMA20", line=dict(color="blue")
))

# Liquidity Path
dt_x, dt_y, labels = zip(*liq_path)
fig.add_trace(go.Scatter(
    x=dt_x, y=dt_y,
    mode="lines+markers+text",
    name="Liquidity Path",
    text=labels,
    textposition="top center",
    line=dict(color="orange", dash="dot")
))

fig.update_layout(
    title="Candlestick Chart + SMA20 + Liquidity Wall Path",
    xaxis_rangeslider_visible=False,
    height=600
)

st.plotly_chart(fig, use_container_width=True)
