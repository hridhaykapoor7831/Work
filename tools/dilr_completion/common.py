import json,re,glob,os
CH={'C2':'Logical_Reasoning_Based_on_Arrangements','C3':'Rankings','C4':'Team_Formations','C5':'Quant_Reasoning','C6':'Generic_Puzzles','C7':'Routes_and_Network','C8':'Set_Theory_and_Venn_Diagrams','C9':'Cubes_and_Dices','C10':'Games_and_Tournament','C11':'Puzzles_on_Scheduling_','C12':'Cryptarithmetic','D2':'Tables','D3':'Bar_Graphs','D4':'Line_Graphs','D5':'Pie_Charts'}
def norm(s): return re.sub(r'[^a-z0-9]','',s.lower())
_ST={}
def stream(ch):
    if ch in _ST: return _ST[ch]
    d=os.path.join(S,'books/pages',CH[ch]); out=[]
    fs=sorted(glob.glob(d+'/p-*.cols.json'),key=lambda f:int(re.search(r'p-(\d+)',f).group(1)))
    for pi,f in enumerate(fs):
        J=json.load(open(f))
        for L in J['lines']: L['page']=f.replace('.cols.json','.png'); L['pi']=pi; out.append(L)
    _ST[ch]=out; return out
