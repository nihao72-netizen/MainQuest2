import numpy as np, os, json, sys
from PIL import Image
IDS=['4375207e','aefb8e9f','c21cded0','66b925ae','105c48c8','2d783338','425f3ab2','60f7fd76','b11b96e2','fa04e75a']
OUT="/home/claude/auto/out"; os.makedirs(OUT,exist_ok=True)
def load(i):
    im=np.array(Image.open(f"/mnt/user-data/uploads/{i}-image.png").convert("RGB")).astype(int)
    r,g,b=im[...,0],im[...,1],im[...,2]
    green=(g>50)&(g<140)&(r<40)&(b<40)
    H,W=r.shape
    gy=np.where(green[:, :W//2].mean(1)>0.5)[0]; ybot=gy.min() if len(gy) else H
    gx=np.where(green[:ybot].mean(0)>0.5)[0]; xr=gx.min() if len(gx) else W
    red=(r>190)&(g<120)&(b<120); blue=(b>170)&(r<110)&(g<170)
    m=(red|blue); m[ybot:]=False; m[:,xr-2:]=False; m[:50,:560]=False
    clean=np.full_like(im,255); clean[red&m]=im[red&m]; clean[blue&m]=im[blue&m]
    return clean.astype(np.uint8),m,ybot,xr
def series(m):
    W=m.shape[1]; xs=[];hi=[];lo=[]
    for x in range(W):
        ys=np.where(m[:,x])[0]
        if len(ys): xs.append(x);hi.append(ys.min());lo.append(ys.max())
    xs=np.array(xs);hi=np.array(hi);lo=np.array(lo)
    return xs,-(hi+lo)/2.0,-hi,-lo   # price-like (up positive)
def zigzag(v,th):
    n=len(v); hi=lo=0; trend=0; piv=[]
    for i in range(1,n):
        if trend==0:
            if v[i]>v[hi]: hi=i
            if v[i]<v[lo]: lo=i
            if v[hi]-v[lo]>th:
                if hi>lo: piv.append((lo,'L')); trend=1; ext=hi
                else: piv.append((hi,'H')); trend=-1; ext=lo
        elif trend==1:
            if v[i]>v[ext]: ext=i
            elif v[ext]-v[i]>th: piv.append((ext,'H')); trend=-1; ext=i
        else:
            if v[i]<v[ext]: ext=i
            elif v[i]-v[ext]>th: piv.append((ext,'L')); trend=1; ext=i
    if trend!=0: piv.append((ext,'H' if trend==1 else 'L'))
    return piv
def find(piv,v):
    res=[]
    P=[(i,t,v[i]) for i,t in piv]
    for sgn,names in [(1,("쌍바닥","삼중바닥","역헤드앤숄더","N자형")),(-1,("쌍봉","삼중천장","헤드앤숄더","역N자형"))]:
        # sgn=1 bottoms: work in u=v ; sgn=-1 tops: u=-v and swap H/L
        Lt='L' if sgn==1 else 'H'
        u=lambda k: sgn*P[k][2]
        for k in range(len(P)):
            if P[k][1]==Lt: continue  # start at a 'high' (in u space)
            # double: H0 L1 H1 L2 H2
            if k+4<len(P):
                H0,L1,H1,L2,H2=[u(k+j) for j in range(5)]
                low=min(L1,L2); d=H1-low
                if d>0 and abs(L1-L2)<=0.22*d and H0>H1+0.3*d and H2>H1 and H0-low>1.3*d:
                    res.append((names[0],P[k][0],P[k+4][0]))
            if k+6<len(P):
                H0,L1,H1,L2,H2,L3,H3=[u(k+j) for j in range(7)]
                neck=(H1+H2)/2; lows=[L1,L2,L3]; low=min(lows); d=neck-low
                if d>0 and H0>neck+0.3*d and H3>max(H1,H2) and abs(H1-H2)<0.35*d:
                    if max(lows)-low<=0.25*d:
                        res.append((names[1],P[k][0],P[k+6][0]))
                    elif L2==low and (L1-L2)>=0.3*d and (L3-L2)>=0.3*d and abs(L1-L3)<=0.35*d:
                        res.append((names[2],P[k][0],P[k+6][0]))
        for k in range(len(P)-3):
            if P[k][1]!=Lt: continue
            L0,H1,L1,H2=[u(k+j) for j in range(4)]
            rise=H1-L0; pull=H1-L1
            if rise>0 and H2>H1+0.15*rise and L1>L0 and rise/3<=pull<=0.75*rise and (H2-L1)>=0.8*rise:
                res.append((names[3],P[k][0],P[k+3][0]))
    return res
def trends(xs,v,rng):
    res=[]
    n=len(xs)
    for w in (450,700):
        for s in range(0,n-w,w//2):
            seg=v[s:s+w]; r=seg.max()-seg.min()
            net=seg[-1]-seg[0]
            run_max=np.maximum.accumulate(seg); dd=(run_max-seg).max()
            run_min=np.minimum.accumulate(seg); du=(seg-run_min).max()
            if r>0.2*rng and net>0.75*r and dd<0.25*r: res.append(("상승추세",s,s+w-1))
            elif r>0.2*rng and -net>0.75*r and du<0.25*r: res.append(("하락추세",s,s+w-1))
            elif r<0.25*rng and abs(net)<0.3*r:
                pv=zigzag(seg,0.35*r)
                if len(pv)>=5: res.append(("횡보",s,s+w-1))
    return res
def crop(clean,m,x0,x1,ybot):
    H,W=m.shape; w=x1-x0; x0=max(0,int(x0-0.04*w)); x1=min(W-1,int(x1+0.04*w))
    ys=np.where(m[:,x0:x1+1].any(1))[0]; y0,y1=ys.min(),ys.max(); h=y1-y0
    pad=int(0.05*h)+4; y0=max(0,y0-pad); y1=min(ybot-1,y1+pad)
    im=Image.fromarray(clean[y0:y1+1,x0:x1+1]); w,h=im.size
    tw=max(w,int(1.5*h)); th=max(h,int(w/1.5)); ox=(tw-w)//2; oy=(th-h)//2
    canvas=Image.new("RGB",(tw,th),"white"); canvas.paste(im,(ox,oy))
    sc=450/tw
    return canvas.resize((450,300),Image.LANCZOS),(lambda X,Y:((X-x0+ox)*sc,(Y-y0+oy)*sc))
from collections import Counter
allc=[]
for n,i in enumerate(IDS,1):
    clean,m,ybot,xr=load(i)
    xs,v,_,_=series(m); rng=v.max()-v.min()
    found=[]
    for th in (0.08,0.12,0.17):
        piv=zigzag(v,th*rng)
        for c,a,b in find(piv,v):
            if 300<=xs[b]-xs[a]<=2000: found.append((c,xs[a],xs[b],[(int(xs[i]),float(-v[i])) for i,t in piv if a<=i<=b]))
    for c,a,b in trends(xs,v,rng): found.append((c,xs[a],xs[b],[]))
    pri={"역헤드앤숄더":0,"헤드앤숄더":0,"삼중바닥":1,"삼중천장":1,"쌍바닥":2,"쌍봉":2,"N자형":3,"역N자형":3,"상승추세":4,"하락추세":4,"횡보":4}
    kept=[]; per=Counter()
    for c,a,b,pv in sorted(found,key=lambda t:(pri[t[0]],-(t[2]-t[1]))):
        dup=False
        for c2,a2,b2,_ in kept:
            inter=max(0,min(b,b2)-max(a,a2)); uni=max(b,b2)-min(a,a2)
            if inter/uni>0.5: dup=True;break
        if dup or per[c]>=3: continue
        kept.append((c,a,b,pv)); per[c]+=1
    for c,a,b,pv in kept:
        img,T=crop(clean,m,a,b,ybot)
        allc.append(dict(src=n,cls=c,x0=int(a),x1=int(b),img=img,pv=[T(X,Y) for X,Y in pv]))
from collections import Counter
print(Counter(d['cls'] for d in allc))
cnt=Counter()
meta=[]
for d in allc:
    cnt[d['cls']]+=1; k=cnt[d['cls']]
    os.makedirs(f"{OUT}/{d['cls']}",exist_ok=True)
    fn=f"{d['cls']}_{k:02d}_원본{d['src']:02d}.png"; d['img'].save(f"{OUT}/{d['cls']}/{fn}")
    meta.append(dict(file=f"{d['cls']}/{fn}",src=d['src'],x0=d['x0'],x1=d['x1'],pv=d['pv']))
json.dump(meta,open("/home/claude/auto/meta.json","w"),ensure_ascii=False,indent=1)
