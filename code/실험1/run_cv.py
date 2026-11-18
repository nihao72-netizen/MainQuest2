import sys,json,os,shutil,random,numpy as np; sys.path.insert(0,"/home/claude/exp")
from common import *
from PIL import Image
from sklearn.model_selection import GroupKFold
meta=json.load(open("/home/claude/exp/meta.json"))
paths=[m["path"] for m in meta]; y=[m["cls"] for m in meta]; groups=[m["group"] if not m["manual"] else m["group"] for m in meta]
import rule
res={"rule":[None]*len(meta),"yolo":[None]*len(meta)}
for i,p in enumerate(paths): res["rule"][i]=rule.predict(p)
from ultralytics import YOLO
gkf=GroupKFold(n_splits=5)
for fold,(tr,te) in enumerate(gkf.split(paths,y,groups)):
    root=f"/home/claude/exp/yolo_f{fold}"; shutil.rmtree(root,ignore_errors=True)
    for sp in ("train","val"):
        for c in CLASSES: os.makedirs(f"{root}/{sp}/{c}",exist_ok=True)
    for i in tr:
        im=Image.open(paths[i]); c=y[i]
        im.save(f"{root}/train/{c}/{i:03d}.png"); flip(im).save(f"{root}/train/{MIRROR[c]}/{i:03d}_f.png")
    for i in te: Image.open(paths[i]).save(f"{root}/val/{y[i]}/{i:03d}.png")
    model=YOLO("yolo11n-cls.pt")
    model.train(data=root,epochs=40,imgsz=224,batch=16,device="cpu",workers=0,verbose=False,plots=False,seed=0,deterministic=True,project=f"/home/claude/exp/runs",name=f"f{fold}",exist_ok=True,fliplr=0.0,flipud=0.0,erasing=0.0,auto_augment=None,hsv_h=0.0,hsv_s=0.0,hsv_v=0.0)
    names=model.names
    for i in te:
        r=model.predict(paths[i],imgsz=224,device="cpu",verbose=False)[0]
        res["yolo"][i]=names[int(r.probs.top1)]
    print("fold",fold,"done",flush=True)
json.dump(dict(y=y,groups=groups,manual=[m["manual"] for m in meta],paths=paths,**res),open("/home/claude/exp/cv_results.json","w"),ensure_ascii=False)
for k in ("rule","yolo"):
    acc=np.mean([a==b for a,b in zip(res[k],y)]); dacc=np.mean([direction(a)==direction(b) for a,b in zip(res[k],y)])
    print(k,"11class acc",round(acc,3),"direction acc",round(dacc,3))
