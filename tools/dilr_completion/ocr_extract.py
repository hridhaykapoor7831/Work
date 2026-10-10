import json,sys,base64,os
src,out=sys.argv[1],sys.argv[2]
emb=bank=None
with open(src,encoding='utf-8') as f:
    for line in f:
        if line.startswith('var EMB='): emb=json.loads(line[len('var EMB='):].rstrip().rstrip(';'))
        elif line.startswith('var BANK_DB='): bank=json.loads(line[len('var BANK_DB='):].rstrip().rstrip(';'))
        if emb is not None and bank is not None: break
book=[x for x in bank['dilr'] if x.get('pool')=='book']
meta=[]
for x in book:
    sc=x.get('scans') or ([x.get('scan')] if x.get('scan') else ([x.get('img')] if x.get('img') else []))
    keys=[]
    for p in sc:
        k=p.split('/')[-1]
        if k in emb:
            data=emb[k].split(',',1)[1]; fn=os.path.join(out,'img',x['uid']+'__'+str(len(keys))+'.'+k.split('.')[-1])
            open(fn,'wb').write(base64.b64decode(data)); keys.append(fn)
    meta.append({'uid':x['uid'],'n':len(x.get('qs',[])),'nlive':len([q for q in x.get('qs',[]) if not q.get('drop')]),'lod':x.get('lod'),'topic':x.get('topic'),'scans':sc,'files':keys})
json.dump(meta,open(os.path.join(out,'meta.json'),'w'),indent=0)
print('book sets',len(book),'with image',sum(1 for m in meta if m['files']),'multi-scan',sum(1 for m in meta if len(m['scans'])>1))
print('pyq sets',sum(1 for x in bank['dilr'] if x.get('pool')=='pyq'))
