import json, os, time
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from config import ENTRY_ALERT_COOLDOWN_HOURS, INSIDE_ALERT_HOURS, MIN_FVG_POINTS, MIN_DISPLACEMENT_BODY_ATR, HISTORY_PERIOD
STATE_FILE=Path('state.json'); UNIVERSE_FILE=Path('universe.csv')
def now_iso(): return datetime.now(timezone.utc).isoformat()
def load_state():
    try: return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    except: return {}
def save_state(s): STATE_FILE.write_text(json.dumps(s,indent=2))
def send_telegram(text):
    url=f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage"
    r=requests.post(url,json={'chat_id':os.environ['TELEGRAM_CHAT_ID'],'text':text},timeout=20); r.raise_for_status()
def normalize(d):
    if d is None or d.empty: return None
    if isinstance(d.columns,pd.MultiIndex): d.columns=d.columns.get_level_values(0)
    if not all(c in d.columns for c in ['Open','High','Low','Close']): return None
    return d[['Open','High','Low','Close']].dropna().copy()
def atr(d,n=14):
    h,l,c=d['High'],d['Low'],d['Close']; p=c.shift(1)
    return pd.concat([h-l,(h-p).abs(),(l-p).abs()],axis=1).max(axis=1).rolling(n).mean()
def resample(d,rule): return d.resample(rule).agg({'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()
def bullish_ob(d):
    z=[]; a=atr(d)
    for i in range(1,len(d)):
        p,c=d.iloc[i-1],d.iloc[i]
        if p.Close>=p.Open: continue
        body=c.Close-c.Open
        if body<=0 or c.Close<=p.High: continue
        if pd.notna(a.iloc[i]) and body<MIN_DISPLACEMENT_BODY_ATR*a.iloc[i]: continue
        z.append({'type':'OB','formed':str(d.index[i-1]),'low':float(p.Low),'high':float(p.High)})
    return z
def bullish_fvg(d):
    z=[]
    for i in range(2,len(d)):
        c1,c3=d.iloc[i-2],d.iloc[i]; gap=float(c3.Low-c1.High)
        if gap>=MIN_FVG_POINTS and gap>0: z.append({'type':'FVG','formed':str(d.index[i]),'low':float(c1.High),'high':float(c3.Low)})
    return z
def get_daily(symbol):
    try: return normalize(yf.Ticker(symbol).history(period=HISTORY_PERIOD,interval='1d',auto_adjust=False))
    except Exception as e: print(f'DATA ERROR {symbol}: {e}'); return None
def metadata(symbol):
    out={'sector':'Unknown','industry':'Unknown','cap_category':'Unknown'}
    try:
        info=yf.Ticker(symbol).info or {}; out['sector']=info.get('sector') or 'Unknown'; out['industry']=info.get('industry') or 'Unknown'
        mc=info.get('marketCap');
        if isinstance(mc,(int,float)):
            out['cap_category']='Large Cap' if mc>=200e9 else 'Mid Cap' if mc>=50e9 else 'Small Cap' if mc>=10e9 else 'Micro Cap'
    except Exception as e: print(f'METADATA ERROR {symbol}: {e}')
    return out
def hours_since(ts):
    if not ts:return 1e9
    try:return (datetime.now(timezone.utc)-datetime.fromisoformat(ts)).total_seconds()/3600
    except:return 1e9
def key(s,tf,z): return f"{s}|{tf}|{z['type']}|{z['formed']}|{z['low']:.4f}|{z['high']:.4f}"
def alert(row,tf,z,price,status,meta):
    cap=row.get('cap_category') or meta['cap_category']; sector=row.get('sector') or meta['sector']; industry=row.get('industry') or meta['industry']; index=row.get('index') or '—'
    return '\n'.join(['🚨 BULLISH OB/FVG ALERT','',f"📌 Stock: {row['name']} ({row['symbol']})",f"🏦 Exchange: {row['exchange']}",f"🏭 Sector: {sector}",f"🧩 Industry: {industry}",f"📊 Market Cap: {cap}",f"📈 Index: {index}",'',f"⏱ Timeframe: {tf}",f"🎯 Setup: Bullish {z['type']}",f"💰 Current Price: ₹{price:,.2f}",f"🟢 Zone: ₹{z['low']:,.2f} – ₹{z['high']:,.2f}",f"📅 Formed: {z['formed']}",f"📍 Status: {status}",'','⚠️ Scanner alert only — Not investment advice.'])
def scan(row,state):
    s=str(row['symbol']); d=get_daily(s)
    if d is None or len(d)<100:return 0
    price=float(d.Close.iloc[-1]); n=0
    for tf,rule in [('Monthly','ME'),('3M','QE-DEC')]:
        try:h=resample(d,rule).iloc[:-1]
        except Exception as e: print('RESAMPLE ERROR',s,tf,e); continue
        if len(h)<20:continue
        for z in (bullish_ob(h)+bullish_fvg(h))[-20:]:
            k=key(s,tf,z); inside=z['low']<=price<=z['high']; r=state.get(k,{})
            first=inside and not r.get('inside',False) and k in state
            m=None
            if first and hours_since(r.get('last_entry_ts'))>=ENTRY_ALERT_COOLDOWN_HOURS:
                m=metadata(s); send_telegram(alert(row,tf,z,price,'FIRST ENTRY',m)); r['last_entry_ts']=now_iso(); n+=1
            if inside and hours_since(r.get('last_inside_ts'))>=INSIDE_ALERT_HOURS:
                if m is None:m=metadata(s)
                send_telegram(alert(row,tf,z,price,'STILL INSIDE ZONE',m)); r['last_inside_ts']=now_iso(); n+=1
            r['inside']=inside; state[k]=r
    return n
def main():
    if not os.environ.get('TELEGRAM_BOT_TOKEN') or not os.environ.get('TELEGRAM_CHAT_ID'): raise RuntimeError('Missing Telegram GitHub Secrets')
    if not UNIVERSE_FILE.exists(): raise RuntimeError('universe.csv not found')
    state=load_state(); u=pd.read_csv(UNIVERSE_FILE).fillna(''); print(f'Universe size: {len(u)}'); total=0
    for row in u.to_dict('records'):
        try: total+=scan(row,state)
        except Exception as e: print(f"ERROR {row.get('symbol')}: {e}")
        time.sleep(.25)
    save_state(state); print(f'Finished. Alerts sent: {total}')
if __name__=='__main__':main()
    
