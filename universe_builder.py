from io import StringIO
from pathlib import Path
import re,requests,pandas as pd
OUT=Path('universe.csv'); PAGE='https://www.nseindia.com/static/market-data/securities-available-for-trading'
H={'User-Agent':'Mozilla/5.0 Chrome/125 Safari/537.36','Accept-Language':'en-US,en;q=0.9'}
def get(u):
 r=requests.get(u,headers=H,timeout=30); r.raise_for_status(); return r
def build_bse():
 u='https://api.bseindia.com/BseIndiaAPI/api/LitsOfScripCSVDownload/w'
 h={'User-Agent':'Mozilla/5.0 Chrome/134 Safari/537.36','Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8','Referer':'https://www.bseindia.com/'}
 params={'segment':'Equity','status':'Active','industry':'','Group':'','Scripcode':''}
 r=requests.get(u,params=params,headers=h,timeout=30); r.raise_for_status()
 try: df=pd.read_csv(StringIO(r.content.decode('utf-8')))
 except: df=pd.read_csv(StringIO(r.content.decode('latin1')))
 df.columns=[str(c).strip().lower().replace(' ','_') for c in df.columns]
 def cands(xs):
  for x in xs:
   if x in df.columns:return x
  for c in df.columns:
   if any(x in c for x in xs):return c
  return None
 code=cands(['scrip_code','security_code','scripcode']); sid=cands(['security_id','securityid','symbol']); name=cands(['security_name','securityname','company_name','security_name']); industry=cands(['industry'])
 if not code: raise RuntimeError(f'BSE scrip code column not found: {list(df.columns)}')
 out=pd.DataFrame()
 out['symbol']=df[code].astype(str).str.replace(r'\.0$','',regex=True).str.zfill(6)+'.BO'
 out['exchange']='BSE'
 out['name']=df[name].astype(str).str.strip() if name else df[sid].astype(str).str.strip()
 out['sector']=''
 out['industry']=df[industry].astype(str).str.strip() if industry else ''
 out['cap_category']=''; out['index']=''
 return out.drop_duplicates('symbol')

def main():
 html=get(PAGE).text; links=re.findall(r'https?://[^"\']+?\.csv(?:\?[^"\']*)?',html,re.I)
 bad=('sme','etf','preference','debt','warrant','reit','invit'); links=[x for x in links if not any(b in x.lower() for b in bad)]
 url=next((x for x in links if 'equity' in x.lower()),None) or next((x for x in links if 'secur' in x.lower()),None)
 if not url: raise RuntimeError('NSE equity CSV link not found')
 raw=get(url).content
 try: df=pd.read_csv(StringIO(raw.decode('utf-8')))
 except: df=pd.read_csv(StringIO(raw.decode('latin1')))
 df.columns=[str(c).strip().lower().replace(' ','_') for c in df.columns]
 def col(names):
  for n in names:
   if n in df.columns:return n
  for c in df.columns:
   if any(n in c for n in names):return c
  return None
 sym=col(['symbol','trading_symbol','ticker']); name=col(['name_of_company','company_name','name','security_name']); series=col(['series'])
 if not sym: raise RuntimeError(f'No symbol column: {list(df.columns)}')
 if series:
  s=df[series].astype(str).str.upper().str.strip(); m=s.isin(['EQ','BE','BZ','SM'])
  if m.any():df=df[m]
 out=pd.DataFrame({'symbol':df[sym].astype(str).str.strip().str.upper()+'.NS','exchange':'NSE','name':df[name].astype(str).str.strip() if name else df[sym].astype(str).str.strip(),'sector':'','industry':'','cap_category':'','index':''}).drop_duplicates('symbol')
 try:
  bse=build_bse()
  out=pd.concat([out,bse],ignore_index=True).drop_duplicates('symbol')
  print(f'BSE active equity symbols added: {len(bse)}')
 except Exception as e:
  print(f'WARNING: BSE universe refresh failed: {e}')
 out.to_csv(OUT,index=False); print(f'Wrote {len(out)} NSE+BSE equity symbols to {OUT}')
if __name__=='__main__':main()
