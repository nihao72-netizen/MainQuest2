import glob,os,json,shutil,numpy as np
from PIL import Image
OUT="/home/claude/exp/ds"; shutil.rmtree(OUT,ignore_errors=True)
def clean(im):
    a=np.array(im.convert("RGB")).astype(int); r,g,b=a[...,0],a[...,1],a[...,2]
    red=(r>170)&(g<140)&(b<140); blue=(b>150)&(r<130)&(g<190)
    c=np.full_like(a,255); c[red]=a[red]; c[blue]=a[blue]
    ys,xs=np.where(red|blue)
    if len(ys): c=c[max(0,ys.min()-4):ys.max()+5, max(0,xs.min()-2):xs.max()+3]
    return Image.fromarray(c.astype(np.uint8))
def to32(im):
    w,h=im.size; tw=max(w,int(1.5*h)); th=max(h,int(w/1.5))
    cv=Image.new("RGB",(tw,th),"white"); cv.paste(im,((tw-w)//2,(th-h)//2)); return cv.resize((450,300),Image.LANCZOS)
items=[]
for f in sorted(glob.glob("/home/claude/auto/out/*/*.png")):
    c=f.split("/")[-2]; g=f.split("원본")[-1][:2]; items.append((f,c,"src"+g,False))
man="/mnt/user-data/uploads/3-8.AI이해하고 사용하기_내 업무 어디에 AI를 넣을까/MainQuest2/data/학습용"
for c in [x for x in os.listdir(man) if x!="없음"]:
    for f in sorted(glob.glob(f"{man}/{c}/*.png")):
        if "원본" in f: continue
        items.append((f,c,"man_"+c+"_"+os.path.basename(f),True))
meta=[]
for k,(f,c,g,m) in enumerate(items):
    im=Image.open(f); im=to32(clean(im) if m else im)
    os.makedirs(f"{OUT}/{c}",exist_ok=True); p=f"{OUT}/{c}/{k:03d}.png"; im.save(p)
    meta.append(dict(path=p,cls=c,group=g,manual=m,orig=f))
json.dump(meta,open("/home/claude/exp/meta.json","w"),ensure_ascii=False,indent=1)
from collections import Counter; print(len(meta),Counter(x['cls'] for x in meta))
