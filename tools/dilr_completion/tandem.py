import json,sys,re
from difflib import SequenceMatcher
S=sys.argv[1]; exec(open(S+'/common.py').read())
for line in open(S+'/v72/streakrunner_v74.html',encoding='utf-8'):
    if line.startswith('var BANK_DB='): bank=json.loads(line[len('var BANK_DB='):].rstrip().rstrip(';'));break
B={x['uid']:x for x in bank['dilr']}
LOC=json.load(open(S+'/locate.json')); M=json.load(open(S+'/img2.json')); C=json.load(open(S+'/complete.json'))
def key(t,o): return norm(t+' '+' '.join(str((o or {}).get(k,'')) for k in 'ABCD'))
out={};bad={}
for u in sorted(M):
    x=B[u]; Q=sorted(LOC[u]['qs'],key=lambda q:q['n'])
    sc=[[SequenceMatcher(None,key(q['text'],q['opts']),key(bq.get('text',''),bq.get('opts'))).ratio() for q in Q] for bq in x['qs']]
    # best assignment existing->book (greedy on scores)
    pairs=sorted(((sc[i][j],i,j) for i in range(len(x['qs'])) for j in range(len(Q))),reverse=True)
    ui=set();uj=set();m={}
    for s,i,j in pairs:
        if i in ui or j in uj: continue
        ui.add(i);uj.add(j);m[i]=(Q[j]['n'],s)
    MAN={'C10-L1-Q34-38':[34,37,38],'C5-L2-Q69-70':[69,70],'C6-L2-Q77-78':[77,78],'D2-L2-Q9-13':[9,10,11,12]}  # checked by eye
    if u in MAN: m={i:(n,1.0) for i,n in enumerate(MAN[u])}
    ok=len(m)==len(x['qs']) and all(s>=0.8 for n,s in m.values())
    # order check: bank qs order must be increasing in book number
    seq=[m[i][0] for i in range(len(x['qs']))] if ok else []
    if ok and seq!=sorted(seq): ok=False
    um=re.search(r'Q(\d+)-(\d+)$',u); 
    if ok and um and int(um.group(2))-int(um.group(1))+1==len(x['qs']) and seq!=list(range(int(um.group(1)),int(um.group(2))+1)): ok=False
    if not ok: bad[u]=[(i,m.get(i)) for i in range(len(x['qs']))]; continue
    have=set(seq); keyed={q['n']:q for q in C[u]['missing'] if q['ans'] and q['src']}
    add=[]
    for q in Q:
        if q['n'] in have: continue
        o=q['opts']; full=sorted(o)==['A','B','C','D'] and all(v.strip() for v in o.values())
        base={'bn':q['n'],'text':'Q%d. %s'%(q['n'],q['text'])}
        if q['n'] in keyed:
            t,a=keyed[q['n']]['ans']
            base.update({'ans':a,'type':t,'opts':o if t=='mcq' else {},'order':['A','B','C','D'] if t=='mcq' else []})
        elif full: base.update({'nokey':1,'ans':'','type':'mcq','opts':o,'order':['A','B','C','D']})
        elif o: base.update({'nokey':1,'ans':'','type':'mcq','opts':{k:k for k in 'ABCD'},'order':['A','B','C','D']})
        else: base.update({'nokey':1,'ans':'','type':'tita','opts':{},'order':[]})
        add.append(base)
    out[u]={'bn':seq,'add':add}
print('sets in tandem',len(out),'| uncertain mapping',len(bad))
for u,v in bad.items(): print('  ',u,v)
from collections import Counter
print(Counter(('keyed' if 'nokey' not in a else a['type']+('-letters' if a['opts'] and a['opts'].get('A')=='A' else '')) for v in out.values() for a in v['add']))
json.dump(out,open(S+'/tandem.json','w'))
