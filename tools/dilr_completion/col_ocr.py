import os,sys,subprocess,glob,csv,io,json
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
B=sys.argv[1]; jobs=[]
for d in sorted(glob.glob(B+'/pages/*/')):
    if d.rstrip('/').endswith('DI'): continue   # DI.pdf duplicates Bar/Line/Pie/Tables chapters
    for png in sorted(glob.glob(d+'p-*.png')):
        if '.col' in png: continue
        jobs.append(png)
def run(png):
    out=png[:-4]+'.cols.json'
    if os.path.exists(out): return
    im=Image.open(png).convert('L'); W,H=im.size; mid=W//2; res=[]
    for ci,(x0,x1) in enumerate([(150,mid),(mid,W-150)]):
        c=im.crop((x0,115,x1,H)); fn=png[:-4]+'.col%d.png'%ci; c.save(fn)
        tsv=subprocess.run(['tesseract',fn,'-','--psm','4','tsv'],capture_output=True,text=True,env=dict(os.environ,OMP_THREAD_LIMIT='1')).stdout
        lines={}
        for r in csv.DictReader(io.StringIO(tsv),delimiter='\t',quoting=csv.QUOTE_NONE):
            if r['level']!='5' or not r['text'].strip(): continue
            k=(int(r['block_num']),int(r['par_num']),int(r['line_num']))
            L=lines.setdefault(k,{'w':[],'l':10**9,'t':10**9,'r':0,'b':0})
            x,y,w,h=int(r['left']),int(r['top']),int(r['width']),int(r['height'])
            L['w'].append(r['text']);L['l']=min(L['l'],x);L['t']=min(L['t'],y);L['r']=max(L['r'],x+w);L['b']=max(L['b'],y+h)
        for k,L in lines.items(): res.append({'col':ci,'x0':x0,'y0':115,'text':' '.join(L['w']),'l':L['l'],'t':L['t'],'r':L['r'],'b':L['b']})
    res.sort(key=lambda z:(z['col'],z['t']))
    json.dump({'W':W,'H':H,'lines':res},open(out,'w'))
with ThreadPoolExecutor(4) as ex: list(ex.map(run,jobs))
print('done',len(jobs))
