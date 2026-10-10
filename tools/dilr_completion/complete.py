import json,sys,re
from difflib import SequenceMatcher
S=sys.argv[1]; exec(open(S+'/common.py').read())
HTML=S+'/v72/streakrunner_v73.html'
for line in open(HTML,encoding='utf-8'):
    if line.startswith('var BANK_DB='): bank=json.loads(line[len('var BANK_DB='):].rstrip().rstrip(';'));break
LOC=json.load(open(S+'/locate.json'))
LODH=re.compile(r'Level\s+of\s+Difficulty\s*\(\s*([Il1|]{1,3})\s*\)',re.I)
PAIR=re.compile(r'(?<![\d])(\d{1,3})\s*\.\s*(\(\s*[a-dA-D]\s*\)|[^\s(][^\s]*)?')
def keyrow(t):
    ps=[(int(n),(v or '').strip()) for n,v in PAIR.findall(t)]
    if len(ps)<2: return None
    ns=[p[0] for p in ps]
    if all(ns[i+1]==ns[i]+1 for i in range(len(ns)-1)) and len(re.sub(r'[\d.()\sa-dA-D]','',t))<25: return ps
    return None
def parse_keys(ch):
    St=stream(ch); blocks=[]; lod=None; cur=None; mode=None
    for L in St:
        t=L['text']
        if re.search(r'SOLUTIONS\s+AND',t,re.I): mode='sol'
        h=LODH.search(t)
        if h: lod=len(h.group(1)); cur=None; continue
        r=keyrow(t)
        if r:
            if cur is None or r[0][0]<=cur['last']: cur={'lod':lod,'ans':{},'last':0,'pi':L['pi']}; blocks.append(cur)
            for n,v in r:
                if v: cur['ans'].setdefault(n,v)
            cur['last']=r[0][0]
    return blocks
def parse_sols(ch):
    St=stream(ch); out={}; lod=None; insol=False; qn=None
    for L in St:
        t=L['text']
        if re.search(r'SOLUTIONS\s+AND',t,re.I): insol=True; continue
        h=LODH.search(t)
        if h: lod=len(h.group(1)); qn=None; continue
        if not insol or not lod: continue
        qm=re.match(r'^\s*(\d{1,3})\s*[.,]\s',t)
        if qm: qn=int(qm.group(1))
        om=re.search(r'option\s*\(\s*([a-dA-D])\s*\)\s*(?:is|was)?\s*(?:the\s*)?correct',t,re.I) or re.search(r'hence,?\s*option\s*\(\s*([a-dA-D])\s*\)',t,re.I)
        if qn and om: out.setdefault(lod,{}).setdefault(qn,om.group(1).upper())
    return out
def val2ans(v,opts):
    v=v.strip()
    m=re.fullmatch(r'\(\s*([a-dA-D])\s*\)',v)
    if m: return ('mcq',m.group(1).upper())
    if opts:
        best=max(opts.items(),key=lambda kv:SequenceMatcher(None,norm(v),norm(kv[1])).ratio())
        if SequenceMatcher(None,norm(v),norm(best[1])).ratio()>=0.75: return ('mcq',best[0])
        return None
    if re.fullmatch(r'-?\d+(\.\d+)?',v): return ('tita',v)
    return None
KB={ch:parse_keys(ch) for ch in CH}; SB={ch:parse_sols(ch) for ch in CH}
B={x['uid']:x for x in bank['dilr']}
OUT={};stat={}
for u,v in LOC.items():
    x=B[u]; ch=u.split('-')[0]; lod=int(re.search(r'-L(\d)-',u).group(1))
    rec={'status':None,'reasons':[]}
    want=list(range(v['a'],v['b']+1))
    if v['found']!=want: rec['reasons'].append('numbers not all found on pages: found %s of %s'%(v['found'],want))
    # map present
    bt=[norm(q.get('text','')+' '+' '.join(str((q.get('opts') or {}).get(k,'')) for k in 'ABCD')) for q in x['qs']]
    pairs=sorted(((SequenceMatcher(None,norm(q['text']+' '+' '.join(q['opts'].get(k,'') for k in 'ABCD')),b_).ratio(),q['n'],bi) for q in v['qs'] for bi,b_ in enumerate(bt)),reverse=True)
    usedq=set();usedb=set();present={}
    for sc,n,bi in pairs:
        if sc<0.8 or n in usedq or bi in usedb: continue
        usedq.add(n);usedb.add(bi);present[n]=bi
    if len(present)!=len(x['qs']): rec['reasons'].append('could only match %d of %d existing questions'%(len(present),len(x['qs'])))
    missing=[q for q in v['qs'] if q['n'] not in present]
    # choose answer sources that agree with bank on present questions
    def check(src):
        ok=bad=0
        for n,bi in present.items():
            bq=x['qs'][bi]; sv=src.get(n)
            if sv is None: continue
            a=val2ans(sv,bq.get('opts')) if isinstance(sv,str) and not re.fullmatch(r'[A-D]',sv) else ('mcq',sv)
            if a is None: continue
            if str(a[1]).strip().lower()==str(bq.get('ans','')).strip().lower(): ok+=1
            else: bad+=1
        return ok,bad
    keyc=[(check(b['ans']),b) for b in KB[ch] if b['lod']==lod or b['lod'] is None]
    keyc=[(c,b) for c,b in keyc if c[0]>=1 and c[1]==0 and all(n in b['ans'] or True for n in want)]
    solsrc=SB[ch].get(lod,{}); sc_=check(solsrc)
    sol_ok=sc_[1]==0
    adds=[]
    for q in missing:
        a=None;src=None
        for c,b in sorted(keyc,key=lambda z:-z[0][0]):
            if q['n'] in b['ans']:
                a=val2ans(b['ans'][q['n']],q['opts'])
                if a: src='key (checked on %d)'%c[0]; break
        if a is None and sol_ok and q['n'] in solsrc and q['opts']:
            a=('mcq',solsrc[q['n']]); src='solutions (checked on %d)'%sc_[0]
        if a and a[0]=='mcq' and len(q['opts'])<4: a=None; rec['reasons'].append('Q%d options incomplete on page'%q['n'])
        if a is None: rec['reasons'].append('Q%d: no checked answer in your PDFs'%q['n'])
        adds.append({'n':q['n'],'text':q['text'],'opts':q['opts'],'ans':a,'src':src,'lines':q['lines']})
    rec['present']=sorted(present); rec['missing']=adds
    rec['status']='ready' if not rec['reasons'] and missing else 'blocked'
    OUT[u]=rec; stat[rec['status']]=stat.get(rec['status'],0)+1
json.dump(OUT,open(S+'/complete.json','w'),indent=0)
print(stat, 'missing qs ready:',sum(len(r['missing']) for r in OUT.values() if r['status']=='ready'))
from collections import Counter
c=Counter(re.sub(r'Q\d+','Q#',re.sub(r'\[.*','',z)) for r in OUT.values() for z in r['reasons']);print(c.most_common())
