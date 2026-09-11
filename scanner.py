import json, os, time
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import requests
import yfinance as yf

from config import (
    ENTRY_ALERT_COOLDOWN_HOURS,
    INSIDE_ALERT_HOURS,
    MIN_FVG_POINTS,
    MIN_DISPLACEMENT_BODY_ATR,
    HISTORY_PERIOD,
)

STATE_FILE = Path("state.json")
UNIVERSE_FILE = Path("universe.csv")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def send_telegram(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=20)
    r.raise_for_status()


def normalize(df):
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    needed = ["Open", "High", "Low", "Close"]
    df = df[[c for c in needed if c in df.columns]].dropna().copy()
    return df


def resample_htf(daily, rule):
    x = daily.copy()
    # Use calendar period aggregation.
    out = x.resample(rule).agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
    }).dropna()
    return out


def atr(df, n=14):
    h, l, c = df["High"], df["Low"], df["Close"]
    prev = c.shift(1)
    tr = pd.concat([(h-l), (h-prev).abs(), (l-prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def bullish_order_blocks(htf):
    # Definition:
    # last bearish candle before a bullish displacement candle
    # that closes above the previous candle high.
    z = []
    a = atr(htf)
    for i in range(1, len(htf)):
        prev = htf.iloc[i-1]
        cur = htf.iloc[i]
        if prev["Close"] >= prev["Open"]:
            continue
        body = cur["Close"] - cur["Open"]
        if body <= 0 or cur["Close"] <= prev["High"]:
            continue
        if pd.notna(a.iloc[i]) and body < MIN_DISPLACEMENT_BODY_ATR * a.iloc[i]:
            continue
        z.append({
            "type": "OB",
            "formed": str(htf.index[i-1]),
            "low": float(prev["Low"]),
            "high": float(prev["High"]),
        })
    return z


def bullish_fvgs(htf):
    # Definition:
    # Candle 3 Low > Candle 1 High.
    z = []
    for i in range(2, len(htf)):
        c1, c2, c3 = htf.iloc[i-2], htf.iloc[i-1], htf.iloc[i]
        gap = float(c3["Low"] - c1["High"])
        if gap >= MIN_FVG_POINTS and gap > 0:
            z.append({
                "type": "FVG",
                "formed": str(htf.index[i]),
                "low": float(c1["High"]),
                "high": float(c3["Low"]),
            })
    return z


def current_price(symbol):
    t = yf.Ticker(symbol)
    # Fast info is not available/reliable for every symbol.
    try:
        p = t.fast_info.get("last_price")
        if p is not None and np.isfinite(float(p)):
            return float(p)
    except Exception:
        pass
    d = t.history(period="2d", interval="1d", auto_adjust=False)
    if d is None or d.empty:
        return None
    return float(d["Close"].dropna().iloc[-1])


def get_daily(symbol):
    t = yf.Ticker(symbol)
    d = t.history(period=HISTORY_PERIOD, interval="1d", auto_adjust=False)
    return normalize(d)


def zone_key(symbol, tf, zone):
    return f"{symbol}|{tf}|{zone['type']}|{zone['formed']}|{zone['low']:.4f}|{zone['high']:.4f}"


def in_zone(price, zone):
    return zone["low"] <= price <= zone["high"]


def fmt(x):
    return f"{x:,.2f}"


def scan_symbol(symbol, exchange, name, state):
    daily = get_daily(symbol)
    if daily is None or len(daily) < 100:
        return 0

    price = current_price(symbol)
    if price is None:
        return 0

    results = 0
    for tf, rule in [("Monthly", "ME"), ("3M", "QE-DEC")]:
        try:
            htf = resample_htf(daily, rule)
        except Exception:
            continue
        if len(htf) < 20:
            continue

        # Drop the currently forming HTF candle; only closed zones are used.
        htf = htf.iloc[:-1].copy()

        zones = bullish_order_blocks(htf) + bullish_fvgs(htf)

        for zone in zones[-20:]:
            key = zone_key(symbol, tf, zone)
            inside = in_zone(price, zone)
            rec = state.get(key, {})
            was_inside = bool(rec.get("inside", False))
            last_entry = rec.get("last_entry_ts")
            last_inside = rec.get("last_inside_ts")

            # FIRST ENTRY: outside on previous scan, inside now.
            first_entry = inside and not was_inside
            # If state is missing, don't call the first-ever observation an entry.
            if key not in state and inside:
                first_entry = False

            def hours_since(ts):
                if not ts:
                    return 1e9
                try:
                    old = datetime.fromisoformat(ts)
                    return (datetime.now(timezone.utc) - old).total_seconds()/3600
                except Exception:
                    return 1e9

            if first_entry and hours_since(last_entry) >= ENTRY_ALERT_COOLDOWN_HOURS:
                msg = (
                    f"🚨 FIRST ENTRY — {tf} {zone['type']}\\n\\n"
                    f"Stock: {name} ({symbol})\\n"
                    f"Exchange: {exchange}\\n"
                    f"Zone: ₹{fmt(zone['low'])} – ₹{fmt(zone['high'])}\\n"
                    f"Current price: ₹{fmt(price)}\\n"
                    f"Formed: {zone['formed']}\\n\\n"
                    f"Price has entered the zone for the first time.\\n"
                    f"⚠️ Not investment advice."
                )
                send_telegram(msg)
                rec["last_entry_ts"] = now_iso()
                results += 1

            # While inside: one status alert every INSIDE_ALERT_HOURS.
            if inside and hours_since(last_inside) >= INSIDE_ALERT_HOURS:
                msg = (
                    f"🟢 STILL INSIDE ZONE — {tf} {zone['type']}\\n\\n"
                    f"Stock: {name} ({symbol})\\n"
                    f"Zone: ₹{fmt(zone['low'])} – ₹{fmt(zone['high'])}\\n"
                    f"Current price: ₹{fmt(price)}\\n"
                    f"⚠️ Not investment advice."
                )
                send_telegram(msg)
                rec["last_inside_ts"] = now_iso()
                results += 1

            rec["inside"] = inside
            state[key] = rec

    return results


def main():
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID GitHub Secrets")

    state = load_state()
    u = pd.read_csv(UNIVERSE_FILE)

    total = 0
    for row in u.itertuples(index=False):
        try:
            total += scan_symbol(str(row.symbol), str(row.exchange), str(row.name), state)
        except Exception as e:
            print(f"ERROR {row.symbol}: {e}")
        # Be gentle with free data source.
        time.sleep(0.7)

    save_state(state)
    print(f"Finished. Alerts sent: {total}")


if __name__ == "__main__":
    main()
