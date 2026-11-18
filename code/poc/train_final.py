"""
PoC 1단계: 학습용 사진 전체로 YOLO11n-cls 최종 모델 2개(방향 3분류, 패턴 11분류) 학습

- 교차검증(진행기록 07~10)과 같은 설정: 40 epoch, 224px, seed 0, 뒤집기 늘리기, 다른 늘리기 끔
- 다른 점 1: 모든 사진에 같은 전처리(preprocess.prepare)를 씀 → 실제 판정 때와 같은 길
- 다른 점 2: '시험 점수가 가장 좋은 회차(best.pt)'가 아니라 '마지막 회차(last.pt)'를 저장
             (최종 학습에는 따로 시험할 사진이 없으므로, 어느 회차를 고를지 사진을 보고 정하지 않는다)

실행:  python code/poc/train_final.py            (기본값)
       python code/poc/train_final.py --epochs 40 --imgsz 224 --seed 0
결과:  models/dir3.pt, models/dir3.json, models/cls11.pt, models/cls11.json
"""
import argparse, json, re, shutil, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preprocess as P

ROOT = Path(__file__).resolve().parents[2]   # MainQuest2 폴더

def load_items(data_dir):
    items = []
    for c in P.CLASSES:
        for f in sorted((data_dir / c).glob("*.png")):
            items.append((f, c))
    return items

def build_dataset(items, task, root):
    """YOLO 분류용 폴더(train/val) 만들기. val은 형식상 필요해서 원본 사진을 그대로 넣음 (모델 고르기에 쓰지 않음)"""
    if task == "dir3":
        lab = lambda c: P.DIR_EN[P.direction(c)]
        flab = lambda c: P.DIR_EN[P.DIR_MIRROR[P.direction(c)]]
        names = list(P.DIR_EN.values())
    else:
        lab = lambda c: P.CLS_EN[c]
        flab = lambda c: P.CLS_EN[P.MIRROR[c]]
        names = list(P.CLS_EN.values())
    shutil.rmtree(root, ignore_errors=True)
    for sp in ("train", "val"):
        for n in names:
            (root / sp / n).mkdir(parents=True, exist_ok=True)
    for i, (f, c) in enumerate(items):
        im = P.prepare(P.Image.open(f))
        im.save(root / "train" / lab(c) / f"{i:03d}.png")
        P.flip(im).save(root / "train" / flab(c) / f"{i:03d}_f.png")
        im.save(root / "val" / lab(c) / f"{i:03d}.png")

def train(task, items, args, work):
    from ultralytics import YOLO
    import ultralytics
    ds = work / f"ds_{task}"
    build_dataset(items, task, ds)
    model = YOLO("yolo11n-cls.pt")
    model.train(data=str(ds), epochs=args.epochs, imgsz=args.imgsz, batch=16, device="cpu", workers=0,
                verbose=False, plots=False, seed=args.seed, deterministic=True,
                project=str(work / "runs"), name=task, exist_ok=True,
                fliplr=0.0, flipud=0.0, erasing=0.0, auto_augment=None, hsv_h=0.0, hsv_s=0.0, hsv_v=0.0)
    last = work / "runs" / task / "weights" / "last.pt"
    out_pt = args.out / f"{task}.pt"
    shutil.copy2(last, out_pt)
    counts = {}
    for _, c in items:
        k = P.direction(c) if task == "dir3" else c
        counts[k] = counts.get(k, 0) + 1
    info = dict(
        모델=f"{task}.pt", 종류="방향 3분류" if task == "dir3" else "패턴 11분류",
        학습날짜=datetime.now().isoformat(timespec="seconds"),
        사진수=len(items), 뒤집기포함_학습사진수=len(items) * 2, 클래스별_사진수=counts,
        설정=dict(epochs=args.epochs, imgsz=args.imgsz, seed=args.seed, batch=16, 저장=f"last.pt (마지막 회차)"),
        전처리="code/poc/preprocess.py prepare() — 실제 판정과 같은 함수",
        모델안_이름_한글=P.EN_TO_KO, ultralytics=ultralytics.__version__,
        학습사진=[str(f.relative_to(ROOT)) for f, _ in items],
    )
    (args.out / f"{task}.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_pt

def main():
    ap = argparse.ArgumentParser(description="학습용 사진 전체로 최종 모델 학습")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "학습용")
    ap.add_argument("--out", type=Path, default=ROOT / "models")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--imgsz", type=int, default=224)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    work = args.out / "_work"
    t0 = time.time()
    items = load_items(args.data)
    print(f"학습 사진 {len(items)}장")
    for task in ("dir3", "cls11"):
        p = train(task, items, args, work)
        print(f"저장: {p} ({time.time() - t0:.0f}초)", flush=True)
    shutil.rmtree(work / "ds_dir3", ignore_errors=True); shutil.rmtree(work / "ds_cls11", ignore_errors=True)

if __name__ == "__main__":
    main()
