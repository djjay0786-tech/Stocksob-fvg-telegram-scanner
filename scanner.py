import os
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

from config import HISTORY_PERIOD, REPORT_TITLE
from report_generator import make_report_images

UNIVERSE_FILE = Path('universe.csv')
IST = ZoneInfo('Asia/Kolkata')


def normalize(df):
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    need = ['Open','High','Low','Close']
    if not all(c in df.columns for c in need):
        return None
    return df[need].dropna().copy()


def resample(df, rule):
    return df.resample(rule).agg({'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()


def active_bullish_obs(df):
    """SharQ Fx OB rule: bearish candle, next bullish candle closes above bearish candle high.
    Full bearish candle Low-High is used as the OB zone. Return active zones newest first.
    """
    zones=[]
    for i in range(1, len(df)):
        ob=df.iloc[i-1]
        disp=df.iloc[i]
        if ob.Close < ob.Open and disp.Close > disp.Open and disp.Close > ob.High:
            zones.append({'formed': df.index[i-1], 'low': float(ob.Low), 'high': float(ob.High)})

    # Remove zones invalidated after formation by a later HTF close below zone low.
    active=[]
    for z in zones:
        later=df[df.index > z['formed']]
        if not later.empty and (later['Close'] < z['low']).any():
            continue
        active.append(z)
    return list(reversed(active))


def get_daily(symbol):
    try:
        return normalize(yf.Ticker(symbol).history(period=HISTORY_PERIOD, interval='1d', auto_adjust=False))
    except Exception as e:
        print('DATA ERROR', symbol, e)
        return None


def classify_cap(mcap):
    # Practical report buckets; not official Nifty constituent membership.
    if not isinstance(mcap, (int,float)) or mcap <= 0:
        return 'Unclassified'
    if mcap >= 200e9: return 'Large Cap'
    if mcap >= 50e9: return 'Mid Cap'
    if mcap >= 10e9: return 'Small Cap'
    return 'Micro Cap'


def enrich(symbol):
    sector='—'; industry='—'; mcap=None
    try:
        t=yf.Ticker(symbol)
        try:
            fi=t.fast_info
            mcap=getattr(fi,'market_cap',None)
        except Exception:
            pass
        info=t.info or {}
        sector=info.get('sector') or '—'
        industry=info.get('industry') or '—'
        if not mcap:
            mcap=info.get('marketCap')
    except Exception as e:
        print('META ERROR', symbol, e)
    return sector, industry, classify_cap(mcap)


def scan_row(row):
    symbol=str(row['symbol'])
    daily=get_daily(symbol)
    if daily is None or len(daily) < 100:
        return []
    price=float(daily.Close.iloc[-1])
    found=[]
    for tf, rule in [('1M','ME'),('3M','QE-DEC')]:
        htf=resample(daily,rule)
        if len(htf) < 5: continue
        # Drop current incomplete higher-timeframe candle.
        htf=htf.iloc[:-1]
        for z in active_bullish_obs(htf):
            if z['low'] <= price <= z['high']:
                found.append((tf,z))
                break  # newest active in-zone OB only per timeframe
    if not found:
        return []

    sector, industry, cap=enrich(symbol)
    by_tf={tf:z for tf,z in found}
    tf_text='1M + 3M' if len(by_tf)==2 else next(iter(by_tf))
    zone_text=' | '.join(f"{tf} ₹{z['low']:,.2f}–₹{z['high']:,.2f}" for tf,z in by_tf.items())
    return [{
        'name': row.get('name') or symbol,
        'symbol': symbol,
        'exchange': row.get('exchange') or ('BSE' if symbol.endswith('.BO') else 'NSE'),
        'sector': sector,
        'industry': industry,
        'cap_category': cap,
        'ob': tf_text,
        'status': 'IN ZONE',
        'price': price,
        'zone': zone_text,
    }]


def send_photo(path, caption):
    url=f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendPhoto"
    with open(path,'rb') as f:
        r=requests.post(url,data={'chat_id':os.environ['TELEGRAM_CHAT_ID'],'caption':caption},files={'photo':f},timeout=60)
    r.raise_for_status()


def send_text(text):
    url=f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage"
    r=requests.post(url,json={'chat_id':os.environ['TELEGRAM_CHAT_ID'],'text':text},timeout=30)
    r.raise_for_status()


def main():
    if not os.getenv('TELEGRAM_BOT_TOKEN') or not os.getenv('TELEGRAM_CHAT_ID'):
        raise RuntimeError('Missing Telegram GitHub Secrets')
    if not UNIVERSE_FILE.exists():
        raise RuntimeError('universe.csv not found')
    universe=pd.read_csv(UNIVERSE_FILE).fillna('')
    print('Universe size:',len(universe))
    results=[]
    for n,row in enumerate(universe.to_dict('records'),1):
        try: results.extend(scan_row(row))
        except Exception as e: print('SCAN ERROR',row.get('symbol'),e)
        if n % 100 == 0: print('Scanned',n,'qualified',len(results))
        time.sleep(0.12)

    stamp=datetime.now(IST)
    if not results:
        send_text(f"🦈 {REPORT_TITLE}\n1M & 3M OB Zone Report\n{stamp:%d %b %Y • %I:%M %p IST}\n\nNo stocks are currently inside qualifying bullish OB zones.")
        return
    paths=make_report_images(results, stamp, Path('reports'))
    for cap,path,count,page,pages in paths:
        caption=f"🦈 {REPORT_TITLE} • {cap}\n1M & 3M OB ZONE STOCKS • {count} stocks"
        if pages>1: caption += f" • Page {page}/{pages}"
        send_photo(path,caption)
    print('Reports sent:',len(paths),'Qualified stocks:',len(results))

if __name__=='__main__': main()
