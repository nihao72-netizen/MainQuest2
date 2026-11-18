"""
YOLO11n-cls 방향 3분류(상승/하락/없음) vs 패턴 11분류 (그룹 5겹 교차검증)

두 모델을 같은 묶음(fold), 같은 설정(40 epoch, 224px, 뒤집기 늘리기)으로 나란히 학습해 공정하게 비교한다.
11분류 모델은 예측한 패턴을 방향으로 바꿔서(쌍봉 → 하락 등) 방향 정답률을 잰다.

실행:  python code/yolo_direction/run_yolo_direction.py [결과파일이름.json] [--ckpt best|last]
결과:  진행기록/<결과파일이름> (생략하면 07_방향3분류_실험_결과.json)
회차:  --ckpt last (권장, 11번부터) = 마지막 회차로 채점. 기본값 best = 07~10번과 같은 방식(시험 묶음 점수가
       가장 좋은 회차를 골라 점수가 부풀 수 있음). 어느 쪽을 고르든 다른 회차 점수도 JSON에 함께 저장한다.
"""
import json, re, shutil, sys, time
from pathlib import Path
import numpy as np
from PIL import Image
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parents[2]          # MainQuest2 폴더
DATA = ROOT / "data" / "학습용"
OUT = ROOT / "진행기록"
WORK = Path(__file__).resolve().parent / "_work"     # 학습용 임시 폴더 (매번 새로 만듦)
EPOCHS, IMGSZ, SEED = 40, 224, 0

CLASSES = ["쌍바닥","삼중바닥","역헤드앤숄더","N자형","상승추세","쌍봉","삼중천장","헤드앤숄더","역N자형","하락추세","횡보"]
MIRROR = {"쌍바닥":"쌍봉","삼중바닥":"삼중천장","역헤드앤숄더":"헤드앤숄더","N자형":"역N자형","상승추세":"하락추세","횡보":"횡보"}
MIRROR.update({v: k for k, v in list(MIRROR.items())})
UP = {"쌍바닥","삼중바닥","역헤드앤숄더","N자형","상승추세"}
DOWN = {MIRROR[c] for c in UP}
def direction(c): return "상승" if c in UP else ("하락" if c in DOWN else "없음")
DIRS = ["상승", "하락", "없음"]
DIR_MIRROR = {"상승": "하락", "하락": "상승", "없음": "없음"}
# YOLO 폴더 이름은 영어로 (한글 경로 문제 예방)
DIR_EN = {"상승": "up", "하락": "down", "없음": "none"}
EN_DIR = {v: k for k, v in DIR_EN.items()}
CLS_EN = {c: f"c{i:02d}" for i, c in enumerate(CLASSES)}
EN_CLS = {v: k for k, v in CLS_EN.items()}

def clean(im):
    """빨강·파랑 봉만 남기고 3:2 흰 배경, 450x300으로 맞춤 (첫 실험 build.py와 같은 처리)"""
    a = np.array(im.convert("RGB")).astype(int); r, g, b = a[..., 0], a[..., 1], a[..., 2]
    red = (r > 170) & (g < 140) & (b < 140); blue = (b > 150) & (r < 130) & (g < 190)
    c = np.full_like(a, 255); c[red] = a[red]; c[blue] = a[blue]
    ys, xs = np.where(red | blue)
    if len(ys): c = c[max(0, ys.min()-4):ys.max()+5, max(0, xs.min()-2):xs.max()+3]
    return Image.fromarray(c.astype(np.uint8))

def to32(im):
    w, h = im.size; tw, th = max(w, int(1.5*h)), max(h, int(w/1.5))
    cv = Image.new("RGB", (tw, th), "white"); cv.paste(im, ((tw-w)//2, (th-h)//2))
    return cv.resize((450, 300), Image.LANCZOS)

def flip(im):
    """위아래 뒤집고 빨강·파랑 맞바꿈 → 반대 패턴"""
    a = np.array(im.convert("RGB"))[::-1][..., [2, 1, 0]].copy()
    return Image.fromarray(a)

def load():
    items = []
    for c in CLASSES:
        for f in sorted((DATA / c).glob("*.png")):
            m = re.search(r"원본(\d+)", f.name)
            group = f"src{m.group(1)}" if m else f"man_{c}_{f.name}"   # 같은 원본 화면은 같은 묶음
            im = Image.open(f).convert("RGB")
            im = to32(im if m else clean(im))       # 자동 자른 사진은 이미 깨끗함, 직접 캡처만 정리
            items.append(dict(file=f, cls=c, group=group, manual=not m, im=im))
    return items

def train_and_predict(items, tr, te, task, fold):
    """task='dir' 이면 3분류, 'cls' 이면 11분류. te 사진들의 예측(한글 라벨)을 돌려줌"""
    from ultralytics import YOLO
    if task == "dir":
        names_en = list(DIR_EN.values()); lab = lambda c: DIR_EN[direction(c)]; flab = lambda c: DIR_EN[DIR_MIRROR[direction(c)]]; back = EN_DIR
    else:
        names_en = list(CLS_EN.values()); lab = lambda c: CLS_EN[c]; flab = lambda c: CLS_EN[MIRROR[c]]; back = EN_CLS
    root = WORK / f"{task}_f{fold}"; shutil.rmtree(root, ignore_errors=True)
    for sp in ("train", "val"):
        for n in names_en: (root / sp / n).mkdir(parents=True, exist_ok=True)
    for i in tr:
        it = items[i]
        it["im"].save(root / "train" / lab(it["cls"]) / f"{i:03d}.png")
        flip(it["im"]).save(root / "train" / flab(it["cls"]) / f"{i:03d}_f.png")
    for i in te:
        items[i]["im"].save(root / "val" / lab(items[i]["cls"]) / f"{i:03d}.png")
    model = YOLO("yolo11n-cls.pt")
    model.train(data=str(root), epochs=EPOCHS, imgsz=IMGSZ, batch=16, device="cpu", workers=0, verbose=False,
                plots=False, seed=SEED, deterministic=True, project=str(WORK / "runs"), name=f"{task}_f{fold}",
                exist_ok=True, fliplr=0.0, flipud=0.0, erasing=0.0, auto_augment=None, hsv_h=0.0, hsv_s=0.0, hsv_v=0.0)
    # model.train() 뒤의 model은 '시험 묶음 점수가 가장 좋았던 회차(best.pt)'다.
    # 시험 묶음을 보고 회차를 고른 것이라 점수가 부풀 수 있어, 마지막 회차(last.pt)로도 함께 채점한다.
    last = YOLO(str(WORK / "runs" / f"{task}_f{fold}" / "weights" / "last.pt"))
    preds = {}
    for i in te:
        x = np.array(items[i]["im"])[..., ::-1]   # BGR 배열로 전달
        preds[i] = {}
        for ck, m in (("best", model), ("last", last)):
            r = m.predict(x, imgsz=IMGSZ, device="cpu", verbose=False)[0]
            preds[i][ck] = back[m.names[int(r.probs.top1)]]
    return preds

def summarize(items, pred_cls, pred_dir):
    y = [it["cls"] for it in items]
    true_dir = [direction(c) for c in y]
    man = [i for i, it in enumerate(items) if it["manual"]]
    def score(pd):  # 방향 예측 리스트 → 정답률
        return dict(전체=round(float(np.mean([a == b for a, b in zip(pd, true_dir)])), 3),
                    직접캡처=f"{sum(pd[i] == true_dir[i] for i in man)}/{len(man)}")
    cls_as_dir = [direction(p) for p in pred_cls]
    return {
        "11분류": dict(패턴정답률=round(float(np.mean([a == b for a, b in zip(pred_cls, y)])), 3),
                     패턴_직접캡처=f"{sum(pred_cls[i] == y[i] for i in man)}/{len(man)}", 방향=score(cls_as_dir)),
        "3분류": dict(방향=score(pred_dir)),
        "늘_상승_찍기": dict(방향=score(["상승"] * len(y))),
        "방향_혼동표": {k: {t: {p: sum(1 for a, b in zip(true_dir, pd) if a == t and b == p) for p in DIRS} for t in DIRS}
                     for k, pd in (("11분류", cls_as_dir), ("3분류", pred_dir))},
    }

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="07_방향3분류_실험_결과.json", help="진행기록 안에 저장할 결과 파일 이름")
    ap.add_argument("--ckpt", choices=["best", "last"], default="best",
                    help="채점에 쓸 회차. best=시험 묶음 점수가 가장 좋은 회차(07~10번 방식, 부풀 수 있음), last=마지막 회차")
    args = ap.parse_args()
    other = "last" if args.ckpt == "best" else "best"
    t0 = time.time()
    items = load()
    y = [it["cls"] for it in items]; groups = [it["group"] for it in items]
    print(f"사진 {len(items)}장, 방향별:", {d: sum(direction(c) == d for c in y) for d in DIRS}, "| 채점 회차:", args.ckpt)
    P = {ck: {"cls": [None] * len(items), "dir": [None] * len(items)} for ck in ("best", "last")}
    for fold, (tr, te) in enumerate(GroupKFold(n_splits=5).split(y, y, groups)):
        for task in ("cls", "dir"):
            for i, p in train_and_predict(items, tr, te, task, fold).items():
                for ck in ("best", "last"): P[ck][task][i] = p[ck]
        print(f"fold {fold} 끝 ({time.time()-t0:.0f}초)", flush=True)

    pred_cls, pred_dir = P[args.ckpt]["cls"], P[args.ckpt]["dir"]
    res = {"설정": dict(epochs=EPOCHS, imgsz=IMGSZ, seed=SEED, folds=5, 채점회차=args.ckpt)}
    res.update(summarize(items, pred_cls, pred_dir))
    res[f"비교_{other}회차"] = summarize(items, P[other]["cls"], P[other]["dir"])
    res["예측"] = [dict(file=str(it["file"].relative_to(ROOT)), 정답=it["cls"], 정답방향=direction(it["cls"]),
                      분류11=P[args.ckpt]["cls"][i], 분류11_방향=direction(P[args.ckpt]["cls"][i]), 분류3=P[args.ckpt]["dir"][i],
                      **{f"분류11_{other}": P[other]["cls"][i], f"분류3_{other}": P[other]["dir"][i]})
                 for i, it in enumerate(items)]
    res["걸린시간_초"] = round(time.time() - t0)
    for ck in (args.ckpt, other):
        s = res if ck == args.ckpt else res[f"비교_{other}회차"]
        print(f"[{ck}] 11분류: 패턴 {s['11분류']['패턴정답률']:.0%}, 방향 {s['11분류']['방향']['전체']:.0%} (직접캡처 {s['11분류']['방향']['직접캡처']})"
              f" | 3분류: 방향 {s['3분류']['방향']['전체']:.0%} (직접캡처 {s['3분류']['방향']['직접캡처']})")
    out = OUT / args.out
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", out)

if __name__ == "__main__":
    main()
