from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

CAPS=['Large Cap','Mid Cap','Small Cap','Micro Cap','Unclassified']
ROWS_PER_PAGE=24
W=1600
ROW_H=54
HEADER_H=250
FOOTER_H=100


def font(size,bold=False):
    paths=['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
           '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf']
    for p in paths:
        try:return ImageFont.truetype(p,size)
        except:pass
    return ImageFont.load_default()


def shark_logo(draw,x,y,s=1):
    # clean stylized shark/fin mark drawn locally so no external asset is required
    pts=[(x,y+44*s),(x+55*s,y+10*s),(x+100*s,y+30*s),(x+145*s,y+8*s),(x+132*s,y+48*s),(x+168*s,y+62*s),(x+125*s,y+70*s),(x+92*s,y+62*s),(x+50*s,y+72*s),(x+70*s,y+54*s)]
    draw.polygon(pts,fill=(64,196,255))
    draw.ellipse((x+117*s,y+36*s,x+124*s,y+43*s),fill=(5,18,35))


def ellipsize(draw,text,f,maxw):
    text=str(text)
    if draw.textlength(text,font=f)<=maxw:return text
    while text and draw.textlength(text+'…',font=f)>maxw:text=text[:-1]
    return text+'…'


def make_one(rows,cap,stamp,out,page,pages,total):
    h=HEADER_H+ROW_H*(len(rows)+1)+FOOTER_H
    im=Image.new('RGB',(W,h),(5,18,35)); d=ImageDraw.Draw(im)
    shark_logo(d,55,45,0.9)
    d.text((230,42),'SharQ Fx',font=font(68,True),fill=(240,248,255))
    d.text((230,120),'NSE + BSE • 1 MONTH & 3 MONTH ORDER BLOCK SCANNER',font=font(30,True),fill=(255,208,72))
    d.text((230,170),f'{cap.upper()} • CURRENTLY INSIDE BULLISH OB ZONES',font=font(25,True),fill=(117,218,255))
    d.text((1180,55),stamp.strftime('%d %b %Y'),font=font(28,True),fill=(240,248,255))
    d.text((1180,100),stamp.strftime('%I:%M %p IST'),font=font(25),fill=(190,210,225))
    d.text((1180,145),f'TOTAL: {total} STOCKS',font=font(25,True),fill=(112,238,160))
    if pages>1:d.text((1180,185),f'PAGE {page}/{pages}',font=font(22),fill=(190,210,225))

    y=HEADER_H
    cols=[('#',55),('STOCK NAME',330),('SYMBOL',230),('SECTOR',260),('OB',150),('STATUS',170),('CMP ₹',170),('OB ZONE ₹',0)]
    xs=[];x=35
    for name,wid in cols:
        xs.append(x);d.text((x,y+12),name,font=font(20,True),fill=(255,255,255));x+=wid
    d.rectangle((25,y,W-25,y+ROW_H),outline=(40,116,180),width=2)
    y+=ROW_H
    for i,r in enumerate(rows,1):
        if i%2==0:d.rectangle((25,y,W-25,y+ROW_H),fill=(9,29,52))
        vals=[str((page-1)*ROWS_PER_PAGE+i),r['name'],r['symbol'],r['sector'],r['ob'],r['status'],f"{r['price']:,.2f}",r['zone'].replace('₹','')]
        widths=[45,315,215,245,135,155,155,350]
        for xx,v,mw in zip(xs,vals,widths):
            f=font(19, v in (r['ob'],r['status']))
            fill=(111,238,159) if v=='IN ZONE' else ((255,208,72) if v in ('1M','3M','1M + 3M') else (232,241,248))
            d.text((xx,y+14),ellipsize(d,v,f,mw),font=f,fill=fill)
        d.line((25,y+ROW_H,W-25,y+ROW_H),fill=(22,62,95),width=1);y+=ROW_H
    d.text((45,y+30),'OB = Order Block   •   1M = Monthly   •   3M = Quarterly   •   IN ZONE = Current price inside active bullish OB zone',font=font(20),fill=(188,208,223))
    d.text((45,y+65),'SharQ Fx scanner report • Not investment advice',font=font(18),fill=(130,155,175))
    out.parent.mkdir(parents=True,exist_ok=True);im.save(out,quality=92)


def make_report_images(results,stamp,outdir):
    outdir=Path(outdir);out=[]
    for cap in CAPS:
        rows=[r for r in results if r['cap_category']==cap]
        if not rows:continue
        rows=sorted(rows,key=lambda r:(r['sector'],r['name']))
        total=len(rows);pages=(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE
        for p in range(pages):
            chunk=rows[p*ROWS_PER_PAGE:(p+1)*ROWS_PER_PAGE]
            path=outdir/f"sharq_fx_{cap.lower().replace(' ','_')}_{p+1}.jpg"
            make_one(chunk,cap,stamp,path,p+1,pages,total)
            out.append((cap,path,total,p+1,pages))
    return out
