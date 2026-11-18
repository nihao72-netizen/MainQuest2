import sys; sys.path.insert(0,"/home/claude/exp"); sys.path.insert(0,"/home/claude/auto")
import numpy as np
from PIL import Image
from common import *
import importlib.util
spec=importlib.util.spec_from_file_location("det","/home/claude/auto/detect.py")
src=open("/home/claude/auto/detect.py").read().split("from collections import Counter\nallc=[]")[0]
det={}; exec(src,det)
def predict(path):
    a=np.array(Image.open(path).convert("RGB")).astype(int); r,g,b=a[...,0],a[...,1],a[...,2]
    m=((r>170)&(g<140)&(b<140))|((b>150)&(r<130)&(g<190))
    xs,v,_,_=det["series"](m); rng=v.max()-v.min(); W=xs.max()-xs.min()
    pri={"역헤드앤숄더":0,"헤드앤숄더":0,"삼중바닥":1,"삼중천장":1,"쌍바닥":2,"쌍봉":2,"N자형":3,"역N자형":3}
    best=None
    for th in (0.12,0.18,0.25,0.33):
        piv=det["zigzag"](v,th*rng)
        for c,s,e in det["find"](piv,v):
            cov=(xs[e]-xs[s])/W
            if cov<0.5: continue
            key=(pri[c],-cov)
            if best is None or key<best[0]: best=(key,c)
    if best: return best[1]
    net=v[-1]-v[0]
    if net>0.5*rng: return "상승추세"
    if -net>0.5*rng: return "하락추세"
    return "횡보"
