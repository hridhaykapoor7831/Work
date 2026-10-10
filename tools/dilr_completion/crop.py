import json,sys,os,re
from PIL import Image,ImageDraw,ImageFont
S=sys.argv[1]; exec(open(S+'/common.py').read())
O=json.load(open(S+'/complete.json')); EL=json.load(open(S+'/eligible.json')); LOC=json.load(open(S+'/locate.json'))
try: F=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',26)
except Exception: F=ImageFont.load_default()
meta={}
for u in EL:
    ch=u.split('-')[0]; St=stream(ch); pieces=[]
    for q in sorted(LOC[u]['qs'],key=lambda z:z['n']):
        groups=[]
        for k in q['lines']:
            L=St[k]; key=(L['page'],L['col'])
            if groups and groups[-1][0]==key and L['t']-groups[-1][2]<260: groups[-1][2]=max(groups[-1][2],L['b'])
            else: groups.append([key,L['t'],L['b'],L])
        for (page,col),t,b,L in groups:
            im=Image.open(page); W,H=im.size; x0=L['x0']; x1=W//2 if col==0 else W-150
            if col==1: x0=W//2
            same=[z for z in St if z['page']==page and z['col']==col]
            prevb=max([z['b'] for z in same if z['b']<=t+2] or [t-12]); nextt=min([z['t'] for z in same if z['t']>=b-2 and z['t']>t] or [b+12])
            pieces.append(im.crop((x0,max(0,L['y0']+max(t-12,prevb+3)),x1,min(H,L['y0']+min(b+12,nextt-3)))).convert('RGB'))
    if not pieces: continue
    w=max(p.width for p in pieces); hdr=70
    canvas=Image.new('RGB',(w,hdr+sum(p.height+18 for p in pieces)),'white')
    d=ImageDraw.Draw(canvas); d.rectangle((0,0,w,hdr-12),fill=(255,243,205))
    d.text((16,18),'Every question of this set, as printed in the book',font=F,fill=(90,60,0))
    y=hdr
    for p in pieces: canvas.paste(p,(0,y)); y+=p.height+18
    if canvas.width>900: canvas=canvas.resize((900,int(canvas.height*900/canvas.width)),Image.LANCZOS)
    fn=os.path.join(S,'img2',u+'-2.webp'); canvas.save(fn,'WEBP',quality=72)
    meta[u]={'file':fn,'kb':os.path.getsize(fn)//1024,'nums':[q['n'] for q in LOC[u]['qs']],'pieces':len(pieces)}
json.dump(meta,open(S+'/img2.json','w'),indent=0)
print('images',len(meta),'total KB',sum(m['kb'] for m in meta.values()),'max KB',max(m['kb'] for m in meta.values()))
