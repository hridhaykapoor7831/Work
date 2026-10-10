import os,sys,subprocess,glob,json
from concurrent.futures import ThreadPoolExecutor
B=sys.argv[1]; jobs=[]
for f in sorted(glob.glob(B+'/pdf/*.pdf')):
    name=os.path.basename(f).split('-',1)[1][:-4]; d=B+'/pages/'+name; os.makedirs(d,exist_ok=True)
    if not glob.glob(d+'/p-*.png'): subprocess.run(['pdftoppm','-r','150','-png',f,d+'/p'],check=True)
    jobs+=sorted(glob.glob(d+'/p-*.png'))
def ocr(png):
    t=png[:-4]+'.txt'
    if not os.path.exists(t):
        open(t,'w').write(subprocess.run(['tesseract',png,'-','--psm','4'],capture_output=True,text=True,env=dict(os.environ,OMP_THREAD_LIMIT='1')).stdout)
    return png
with ThreadPoolExecutor(4) as ex: list(ex.map(ocr,jobs))
print('pages',len(jobs))
