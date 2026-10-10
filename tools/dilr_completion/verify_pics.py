import json,sys,re,subprocess,os
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
S=sys.argv[1]
M=json.load(open(S+'/img2.json')); L=json.load(open(S+'/locate.json')); O=json.load(open(S+'/complete.json'))
meta={m['uid']:m for m in json.load(open(S+'/ocr/meta.json'))}
def ocr(fn):
    png=fn+'.v.png'; im=Image.open(fn).convert('L'); im=im.resize((im.width*2,im.height*2)); im.save(png)
    return subprocess.run(['tesseract',png,'-','--psm','4'],capture_output=True,text=True,env=dict(os.environ,OMP_THREAD_LIMIT='1')).stdout
def nums(t): return set(int(n) for n in re.findall(r'(?m)^\s*[\(\[]?(\d{1,3})\s*[.,]\s',t))
def run(u):
    a,b=L[u]['a'],L[u]['b']; want=set(range(a,b+1))
    t1=ocr(meta[u]['files'][0]); t2=ocr(M[u]['file'])
    n1=nums(t1)&want; n2=nums(t2)&want
    miss=sorted(q['n'] for q in O[u]['missing']); pres=sorted(O[u]['present'])
    # options shown in picture 2 for MCQ-looking missing questions
    optc=len(re.findall(r'\(\s*[a-dA-D]\s*\)',t2))
    return u,{'range':[a,b],'pic1':sorted(n1),'pic2':sorted(n2),'missing':miss,'present':pres,
      'not_shown':sorted(want-n2),'pic2_lacks':sorted(set(miss)-n2),'pic1_lacks':sorted(set(pres)-n1),'opts2':optc}
with ThreadPoolExecutor(4) as ex: R=dict(ex.map(run,sorted(M)))
json.dump(R,open(S+'/verify_pics.json','w'),indent=0)
bad={u:r for u,r in R.items() if r['not_shown']}
print('sets',len(R),'| every number found in pic1+pic2:',len(R)-len(bad),'| sets with a number not read:',len(bad))
for u,r in bad.items(): print(u,'range',r['range'],'not read:',r['not_shown'],'| pic1',r['pic1'],'pic2',r['pic2'])
