import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import ta

# ─────────────────────────────────────────────────────────────
# User Input
# ─────────────────────────────────────────────────────────────
symbol_input = st.text_input("Enter coin symbol (e.g., xrp, btc, eth)", value="xrp").upper()


# ─────────────────────────────────────────────────────────────
# Load Data with Dynamic Symbol
# ─────────────────────────────────────────────────────────────
@st.cache_data
def get_data(symbol_input):
    SYMBOL = f"{symbol_input}USDT"
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": SYMBOL, "interval": "1d", "limit": 90}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers).json()
        if not isinstance(r, list) or len(r) == 0:
            return pd.DataFrame(), SYMBOL
        cols = ['Time', 'Open', 'High', 'Low', 'Close', 'Volume',
                'CloseTime', 'QuoteAssetVolume', 'Trades',
                'TakerBaseVol', 'TakerQuoteVol', 'Ignore']
        df = pd.DataFrame(r, columns=cols)
        df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
        df['Time'] = pd.to_datetime(df['Time'], unit='ms')
        df.set_index('Time', inplace=True)
        return df, SYMBOL
    except Exception as e:
        st.error(f"Failed to fetch data: {e}")
        return pd.DataFrame(), SYMBOL

df, SYMBOL = get_data(symbol_input)

if df.empty:
    st.error("❌ No data returned for this symbol. Please check the symbol and try again.")
    st.stop()


# ─────────────────────────────────────────────────────────────
# Technical Indicators
# ─────────────────────────────────────────────────────────────
df['SMA20'] = ta.trend.sma_indicator(df['Close'], window=20)
df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
macd_line = ta.trend.macd(df['Close'])
macd_signal = ta.trend.macd_signal(df['Close'])
df['MACD_Hist'] = macd_line - macd_signal

px = df['Close'].iloc[-1]
st.metric(f"{SYMBOL} Price", f"${px:.4f}")

signals = []
if df['RSI'].iloc[-1] < 30:
    signals.append("RSI: BUY")
elif df['RSI'].iloc[-1] > 70:
    signals.append("RSI: SELL")
else:
    signals.append("RSI: HOLD")

signals.append("SMA: BUY" if px > df['SMA20'].iloc[-1] else "SMA: SELL")
signals.append("MACD: BUY" if df['MACD_Hist'].iloc[-1] > 0 else "MACD: SELL")

st.subheader("Technical Signals")
st.write("\n".join(signals))


# ─────────────────────────────────────────────────────────────
# Fibonacci Levels
# ─────────────────────────────────────────────────────────────
def get_fib(df):
    recent = df[-30:]
    hi, lo = recent['High'].max(), recent['Low'].min()
    diff = hi - lo
    return {
        "0.0%": lo,
        "23.6%": hi - diff * 0.236,
        "38.2%": hi - diff * 0.382,
        "50.0%": hi - diff * 0.500,
        "61.8%": hi - diff * 0.618,
        "78.6%": hi - diff * 0.786,
        "100.0%": hi
    }

fib = get_fib(df)
st.subheader("Fibonacci Levels")
st.table(pd.DataFrame(list(fib.items()), columns=["Level", "Price"]))


# ─────────────────────────────────────────────────────────────
# Liquidity Walls
# ─────────────────────────────────────────────────────────────
def get_order_book(symbol_input):
    SYMBOL = f"{symbol_input}USDT"
    url = "https://api.binance.com/api/v3/depth"
    params = {"symbol": SYMBOL, "limit": 1000}
    headers = {"User-Agent": "Mozilla/5.0"}
    data = requests.get(url, params=params, headers=headers).json()
    px = df['Close'].iloc[-1]
    bids = [(float(p), float(q), float(p) * float(q)) for p, q in data.get('bids', [])]
    asks = [(float(p), float(q), float(p) * float(q)) for p, q in data.get('asks', [])]
    top_bids = sorted([b for b in bids if b[0] < px], key=lambda x: x[2], reverse=True)[:10]
    top_asks = sorted([a for a in asks if a[0] > px], key=lambda x: x[2], reverse=True)[:10]
    return top_bids, top_asks

top_bids, top_asks = get_order_book(symbol_input)

st.subheader("Top 10 Buy Walls")
for b in top_bids:
    st.write(f"🟢 Support near ${b[0]:.2f} with ${b[2]:,.0f} liquidity")

st.subheader("Top 10 Sell Walls")
for a in top_asks:
    st.write(f"🔴 Resistance near ${a[0]:.2f} with ${a[2]:,.0f} liquidity")


# ─────────────────────────────────────────────────────────────
# Liquidity Summary
# ─────────────────────────────────────────────────────────────
total_buy = sum(b[2] for b in top_bids)
total_sell = sum(a[2] for a in top_asks)

st.subheader("Liquidity Pressure Summary")
if total_buy > total_sell * 1.1:
    st.success(f"🟢 More Buying Pressure (${total_buy:,.0f} vs ${total_sell:,.0f})")
elif total_sell > total_buy * 1.1:
    st.error(f"🔴 More Selling Pressure (${total_sell:,.0f} vs ${total_buy:,.0f})")
else:
    st.info(f"⚪ Balanced Liquidity (${total_buy:,.0f} vs ${total_sell:,.0f})")
