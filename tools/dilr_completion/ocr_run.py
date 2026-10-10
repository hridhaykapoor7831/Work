import json,sys,os,re,subprocess
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
out=sys.argv[1]; meta=json.load(open(os.path.join(out,'meta.json')))
RX=re.compile(r'Questions?\s*(\d+)\s*(?:to|-|–|and)\s*(\d+)',re.I)
def run(m):
    fn=m['files'][0]; im=Image.open(fn).convert('L'); w,h=im.size
    crop=im.crop((0,0,w,max(60,int(h*0.25))))
    if w<1400: crop=crop.resize((crop.width*2,crop.height*2))
    png=fn+'.top.png'; crop.save(png)
    txt=subprocess.run(['tesseract',png,'-','--psm','6'],capture_output=True,text=True).stdout
    mm=RX.search(txt)
    m['ocr']=' '.join(txt.split())[:200]; m['range']=[int(mm.group(1)),int(mm.group(2))] if mm else None
    return m
with ThreadPoolExecutor(4) as ex: res=list(ex.map(run,meta))
json.dump(res,open(os.path.join(out,'ocr.json'),'w'),indent=0)
print('parsed',sum(1 for m in res if m['range']),'of',len(res))
