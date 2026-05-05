
import requests
import pandas as pd
import csv
import os
import time

# ===== 填你的TG信息 =====
TOKEN = "8622148245:AAGkE67IDi9FlwdvytFAjd5EHecADP1S5eQ"
CHAT_ID = "8271499388"

# ===== TG发送 =====
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except:
        pass

# ===== 获取市场数据（已加保护）=====
def get_symbols():
    url = "https://api.binance.com/api/v3/ticker/24hr"

    try:
        res = requests.get(url, timeout=10)
        data = res.json()

        if not isinstance(data, list):
            send("⚠️ Binance API异常")
            return pd.DataFrame()

        df = pd.DataFrame(data)

        df["priceChangePercent"] = pd.to_numeric(df["priceChangePercent"], errors="coerce")
        df["quoteVolume"] = pd.to_numeric(df["quoteVolume"], errors="coerce")

        df = df[df["symbol"].str.endswith("USDT")]
        df = df[df["quoteVolume"] > 5_000_000]

        return df.dropna()

    except Exception as e:
        send(f"⚠️ 获取行情失败: {e}")
        return pd.DataFrame()

# ===== 获取K线（加重试+限速）=====
def get_klines(symbol, interval):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"

    for _ in range(3):  # 重试3次
        try:
            res = requests.get(url, timeout=10)
            data = res.json()

            if not isinstance(data, list):
                time.sleep(1)
                continue

            df = pd.DataFrame(data)
            df[4] = pd.to_numeric(df[4], errors="coerce")
            return df[4].dropna()

        except:
            time.sleep(1)

    return pd.Series()

# ===== RSI =====
def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# ===== 保存信号 =====
def save_signal(symbol, direction, entry):
    file = "signals.csv"
    exists = os.path.exists(file)

    with open(file, "a", newline="") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["symbol", "direction", "entry", "status"])
        writer.writerow([symbol, direction, entry, "open"])

# ===== 检查胜负 =====
def check_results():
    if not os.path.exists("signals.csv"):
        return

    df = pd.read_csv("signals.csv")

    for i, row in df.iterrows():
        if row["status"] != "open":
            continue

        symbol = row["symbol"]
        entry = row["entry"]
        direction = row["direction"]

        prices = get_klines(symbol, "5m")
        if prices.empty:
            continue

        price = prices.iloc[-1]

        if direction == "long":
            if price >= entry * 1.04:
                df.at[i, "status"] = "win"
            elif price <= entry * 0.98:
                df.at[i, "status"] = "loss"

        if direction == "short":
            if price <= entry * 0.96:
                df.at[i, "status"] = "win"
            elif price >= entry * 1.02:
                df.at[i, "status"] = "loss"

    df.to_csv("signals.csv", index=False)

# ===== 胜率统计 =====
def stats():
    if not os.path.exists("signals.csv"):
        return "暂无数据"

    df = pd.read_csv("signals.csv")

    wins = len(df[df["status"] == "win"])
    losses = len(df[df["status"] == "loss"])
    total = wins + losses

    if total == 0:
        return "暂无完成信号"

    winrate = wins / total * 100

    return f"""📊 胜率统计

总交易：{total}
盈利：{wins}
亏损：{losses}
胜率：{winrate:.2f}%
"""

# ===== 分析逻辑 =====
def analyze(symbol):
    def calc(p):
        if p.empty or len(p) < 20:
            return None, None, None
        ma5 = p.rolling(5).mean()
        ma20 = p.rolling(20).mean()
        r = rsi(p)
        return ma5, ma20, r

    p5 = get_klines(symbol, "5m")
    p15 = get_klines(symbol, "15m")
    p1h = get_klines(symbol, "1h")

    if p5.empty or p15.empty or p1h.empty:
        return None

    ma5_5, ma20_5, r5 = calc(p5)
    ma5_15, ma20_15, _ = calc(p15)
    ma5_1h, ma20_1h, _ = calc(p1h)

    if ma20_5 is None:
        return None

    last = p5.iloc[-1]

    score_long = 0
    score_short = 0

    # 趋势
    if ma5_15.iloc[-1] > ma20_15.iloc[-1]: score_long += 1
    if ma5_1h.iloc[-1] > ma20_1h.iloc[-1]: score_long += 1

    if ma5_15.iloc[-1] < ma20_15.iloc[-1]: score_short += 1
    if ma5_1h.iloc[-1] < ma20_1h.iloc[-1]: score_short += 1

    # RSI
    if r5.iloc[-1] > 45: score_long += 1
    if r5.iloc[-1] < 55: score_short += 1

    # 回踩
    if abs(last - ma20_5.iloc[-1]) / last < 0.01:
        score_long += 1
        score_short += 1

    entry_low = round(ma20_5.iloc[-1] * 0.995, 2)
    entry_high = round(ma20_5.iloc[-1] * 1.005, 2)

    # 做多
    if score_long >= 4:
        save_signal(symbol, "long", last)
        return f"""【{symbol} 做多｜{score_long}/5】

价格：{round(last,2)}
入场：{entry_low}-{entry_high}
止损：-2%
止盈：+4%
"""

    # 做空
    if score_short >= 4:
        save_signal(symbol, "short", last)
        return f"""【{symbol} 做空｜{score_short}/5】

价格：{round(last,2)}
入场：{entry_high}-{entry_low}
止损：+2%
止盈：+4%
"""

    return None

# ===== 主程序 =====
def run():
    check_results()

    df = get_symbols()

    if df.empty:
        send("⚠️ 市场数据获取失败")
        return

    top = df.sort_values("priceChangePercent", ascending=False).head(20)

    results = []

    for _, row in top.iterrows():
        msg = analyze(row["symbol"])
        if msg:
            results.append(msg)
        time.sleep(0.3)  # 防止限流

    if results:
        send("\n\n".join(results))

    send(stats())

if __name__ == "__main__":
    run()