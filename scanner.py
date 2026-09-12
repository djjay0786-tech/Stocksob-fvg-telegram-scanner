import json
import os
import time
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import requests
import yfinance as yf

from config import MIN_DISPLACEMENT_BODY_ATR, HISTORY_PERIOD

STATE_FILE = Path('state.json')
UNIVERSE_FILE = Path('universe.csv')


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_state():
    try:
        return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def send_telegram(text):
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage"
    r = requests.post(
        url,
        json={'chat_id': os.environ['TELEGRAM_CHAT_ID'], 'text': text},
        timeout=20,
    )
    r.raise_for_status()


def normalize(df):
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if not all(c in df.columns for c in ['Open', 'High', 'Low', 'Close']):
        return None
    return df[['Open', 'High', 'Low', 'Close']].dropna().copy()


def atr(df, n=14):
    h, l, c = df['High'], df['Low'], df['Close']
    prev_close = c.shift(1)
    tr = pd.concat(
        [h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(n).mean()


def resample(df, rule):
    return df.resample(rule).agg(
        {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}
    ).dropna()


def bullish_ob(df):
    """Bullish OB = last bearish candle before bullish displacement close above its high."""
    zones = []
    a = atr(df)

    for i in range(1, len(df)):
        prev = df.iloc[i - 1]
        cur = df.iloc[i]

        # OB candle must be bearish.
        if prev.Close >= prev.Open:
            continue

        body = cur.Close - cur.Open
        if body <= 0:
            continue

        # Bullish displacement candle closes above previous candle high.
        if cur.Close <= prev.High:
            continue

        # Keep the displacement filter already used by your bot.
        if pd.notna(a.iloc[i]) and body < MIN_DISPLACEMENT_BODY_ATR * a.iloc[i]:
            continue

        zones.append(
            {
                'formed': str(df.index[i - 1]),
                'low': float(prev.Low),
                'high': float(prev.High),
            }
        )

    return zones


def get_daily(symbol):
    try:
        return normalize(
            yf.Ticker(symbol).history(
                period=HISTORY_PERIOD,
                interval='1d',
                auto_adjust=False,
            )
        )
    except Exception as e:
        print(f'DATA ERROR {symbol}: {e}')
        return None


def metadata(symbol):
    out = {
        'sector': 'Unknown',
        'industry': 'Unknown',
        'cap_category': 'Unknown',
    }

    try:
        info = yf.Ticker(symbol).info or {}
        out['sector'] = info.get('sector') or 'Unknown'
        out['industry'] = info.get('industry') or 'Unknown'

        market_cap = info.get('marketCap')
        if isinstance(market_cap, (int, float)):
            if market_cap >= 200e9:
                out['cap_category'] = 'Large Cap'
            elif market_cap >= 50e9:
                out['cap_category'] = 'Mid Cap'
            elif market_cap >= 10e9:
                out['cap_category'] = 'Small Cap'
            else:
                out['cap_category'] = 'Micro Cap'
    except Exception as e:
        print(f'METADATA ERROR {symbol}: {e}')

    return out


def state_key(symbol, timeframe, zone):
    # Separate prefix keeps this OB-Tap scanner independent from the old OB/FVG state.
    return (
        f"OBTAP|{symbol}|{timeframe}|{zone['formed']}|"
        f"{zone['low']:.4f}|{zone['high']:.4f}"
    )


def alert_text(row, timeframe, zone, price, meta):
    cap = row.get('cap_category') or meta['cap_category']
    sector = row.get('sector') or meta['sector']
    industry = row.get('industry') or meta['industry']
    index_name = row.get('index') or '—'

    return '\n'.join(
        [
            '🔥 BULLISH ORDER BLOCK TAP',
            '',
            f"📌 Stock: {row['name']} ({row['symbol']})",
            f"🏦 Exchange: {row['exchange']}",
            f"🏭 Sector: {sector}",
            f"🧩 Industry: {industry}",
            f"📊 Market Cap: {cap}",
            f"📈 Index: {index_name}",
            '',
            f"⏱ Timeframe: {timeframe}",
            '🎯 Setup: Bullish Order Block TAP',
            f"💰 Current Price: ₹{price:,.2f}",
            f"🟢 OB Zone: ₹{zone['low']:,.2f} – ₹{zone['high']:,.2f}",
            f"📅 OB Formed: {zone['formed']}",
            '📍 Status: OB TAPPED',
            '',
            '✅ Only Monthly / 3-Month OB taps are enabled.',
            '⚠️ Scanner alert only — Not investment advice.',
        ]
    )


def scan(row, state):
    symbol = str(row['symbol'])
    daily = get_daily(symbol)

    if daily is None or len(daily) < 100:
        return 0

    price = float(daily.Close.iloc[-1])
    alerts = 0
    meta = None

    # ONLY 1-Month and 3-Month bullish Order Blocks.
    for timeframe, rule in [('1 Month', 'ME'), ('3 Month', 'QE-DEC')]:
        try:
            htf = resample(daily, rule).iloc[:-1]  # closed HTF candles only
        except Exception as e:
            print('RESAMPLE ERROR', symbol, timeframe, e)
            continue

        if len(htf) < 20:
            continue

        # No FVG scan. OB only.
        zones = bullish_ob(htf)[-20:]

        for zone in zones:
            k = state_key(symbol, timeframe, zone)
            rec = state.get(k, {})
            inside = zone['low'] <= price <= zone['high']
            was_inside = bool(rec.get('inside', False))

            # Alert only on a fresh tap: outside -> inside.
            # On the first run, a stock already inside the OB is treated as a tap
            # so the scanner can discover currently tapped stocks immediately.
            if inside and not was_inside:
                if meta is None:
                    meta = metadata(symbol)
                send_telegram(alert_text(row, timeframe, zone, price, meta))
                rec['last_tap_ts'] = now_iso()
                alerts += 1

            # No 24-hour STILL INSIDE repeat alerts.
            rec['inside'] = inside
            state[k] = rec

    return alerts


def main():
    if not os.environ.get('TELEGRAM_BOT_TOKEN') or not os.environ.get('TELEGRAM_CHAT_ID'):
        raise RuntimeError('Missing Telegram GitHub Secrets')

    if not UNIVERSE_FILE.exists():
        raise RuntimeError('universe.csv not found')

    state = load_state()
    universe = pd.read_csv(UNIVERSE_FILE).fillna('')

    print(f'Universe size: {len(universe)}')
    print('Mode: MONTHLY + 3-MONTH BULLISH ORDER BLOCK TAP ONLY')

    total = 0
    for row in universe.to_dict('records'):
        try:
            total += scan(row, state)
        except Exception as e:
            print(f"ERROR {row.get('symbol')}: {e}")

        time.sleep(0.25)

    save_state(state)
    print(f'Finished. OB tap alerts sent: {total}')


if __name__ == '__main__':
    main()
