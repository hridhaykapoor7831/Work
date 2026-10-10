import json,sys,re,glob,os
from difflib import SequenceMatcher
S=sys.argv[1]; HTML=S+'/v72/streakrunner_v73.html'
for line in open(HTML,encoding='utf-8'):
    if line.startswith('var BANK_DB='): bank=json.loads(line[len('var BANK_DB='):].rstrip().rstrip(';'));break
OCR={m['uid']:m for m in json.load(open(S+'/ocr/ocr.json'))}
FL=set(json.load(open(HTML+'.flagged.json')))
CH={'C2':'Logical_Reasoning_Based_on_Arrangements','C3':'Rankings','C4':'Team_Formations','C5':'Quant_Reasoning','C6':'Generic_Puzzles','C7':'Routes_and_Network','C8':'Set_Theory_and_Venn_Diagrams','C9':'Cubes_and_Dices','C10':'Games_and_Tournament','C11':'Puzzles_on_Scheduling_','C12':'Cryptarithmetic','D2':'Tables','D3':'Bar_Graphs','D4':'Line_Graphs','D5':'Pie_Charts'}
def norm(s): return re.sub(r'[^a-z0-9]','',s.lower())
def stream(ch):
    d=os.path.join(S,'books/pages',CH[ch]); out=[]
    fs=sorted(glob.glob(d+'/p-*.cols.json'),key=lambda f:int(re.search(r'p-(\d+)',f).group(1)))
    for pi,f in enumerate(fs):
        J=json.load(open(f))
        for L in J['lines']: L['page']=f.replace('.cols.json','.png'); L['pi']=pi; out.append(L)
    return out
QRX=re.compile(r'^\s*[\(\[]?(\d{1,3})\s*[.,]\s+(\S.*)$')
DRX=re.compile(r'Directions?\s+for\s+Questions?\s*(\d+)(?:\s*(?:to|-|–|and)\s*(\d+))?',re.I)
ORX=re.compile(r'^\s*\(([a-dA-D])\)\s*(.*)$')
res={}
for x in bank['dilr']:
    u=x['uid']
    if u not in FL: continue
    ch=u.split('-')[0]; m=re.search(r'Q(\d+)\s*[–-]\s*(\d+)',x.get('src',''))
    a,b=(int(m.group(1)),int(m.group(2))) if m else tuple(OCR[u]['range'])
    if ch not in CH: res[u]={'err':'no chapter'};continue
    St=stream(ch)
    # candidate headers
    cands=[]
    for i,L in enumerate(St):
        dm=DRX.search(L['text'])
        if dm and int(dm.group(1))==a and (dm.group(2) is None or int(dm.group(2))==b):
            ctx=' '.join(z['text'] for z in St[i:i+6])
            sc=SequenceMatcher(None,norm(ctx)[:250],norm(OCR[u]['ocr'])[:250]).ratio()
            cands.append((sc,i))
    if not cands: res[u]={'err':'header not found','a':a,'b':b};continue
    cands.sort(reverse=True); sc,hi=cands[0]
    # walk questions a..b
    qs={};cur=None;expect=a
    for j in range(hi+1,min(len(St),hi+400)):
        t=St[j]['text']
        if DRX.search(t) or re.search(r'LEVEL OF DIFFICULTY|ANSWER KEY|SOLUTIONS AND',t,re.I): 
            if cur is not None and (DRX.search(t) or qs): break
        qm=QRX.match(t)
        if qm and a<=int(qm.group(1))<=b and int(qm.group(1))>=expect:
            cur=int(qm.group(1)); qs[cur]={'lines':[j],'num':cur}; expect=cur+1; continue
        if qm and int(qm.group(1))>b and qs: break
        if cur is not None: qs[cur]['lines'].append(j)
    out={'a':a,'b':b,'hdr_score':round(sc,2),'hdr':hi,'ncand':len(cands),'nbank':len(x['qs']),'found':sorted(qs)}
    # text/opts per question and match to bank
    bt=[norm(q.get('text','')) for q in x['qs']]
    Q=[]
    for n in sorted(qs):
        lines=[St[k] for k in qs[n]['lines']]
        txt=[];opts={};lastopt=None
        for k,L in enumerate(lines):
            t=L['text'] if k else QRX.match(L['text']).group(2)
            parts=re.split(r'\(([a-dA-D])\)',t)
            if len(parts)>1:
                if parts[0].strip() and lastopt is None: txt.append(parts[0].strip())
                elif parts[0].strip() and lastopt: opts[lastopt]+=' '+parts[0].strip()
                for p in range(1,len(parts),2): lastopt=parts[p].upper(); opts[lastopt]=parts[p+1].strip()
            elif lastopt: opts[lastopt]+=' '+t.strip()
            else: txt.append(t.strip())
        text=' '.join(txt); best=max([SequenceMatcher(None,norm(text),b_).ratio() for b_ in bt] or [0])
        Q.append({'n':n,'text':text,'opts':opts,'match':round(best,2),'lines':qs[n]['lines']})
    out['qs']=Q; res[u]=out
json.dump(res,open(S+'/locate.json','w'),indent=0)
ok=sum(1 for v in res.values() if 'qs' in v)
allfound=sum(1 for v in res.values() if 'qs' in v and len(v['found'])==v['b']-v['a']+1)
cnt_ok=sum(1 for v in res.values() if 'qs' in v and sum(1 for q in v['qs'] if q['match']>=0.6)==v['nbank'])
print('located',ok,'of',len(res),'| all numbers found',allfound,'| present-count matches bank',cnt_ok)
for u,v in list(res.items()):
    if 'err' in v: print(u,v)
