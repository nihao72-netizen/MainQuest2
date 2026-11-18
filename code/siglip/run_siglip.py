"""
SigLIP 2 실험: 제로샷 vs 임베딩+로지스틱 회귀 (그룹 5겹 교차검증)

실행:  python code/siglip/run_siglip.py
결과:  진행기록/06_SigLIP2_실험_결과.json
"""
import json, re, sys
from pathlib import Path
import numpy as np
from PIL import Image
import torch
from transformers import AutoModel, AutoProcessor
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parents[2]          # MainQuest2 폴더
DATA = ROOT / "data" / "학습용"
OUT = ROOT / "진행기록"
MODEL_ID = "google/siglip2-base-patch16-224"

CLASSES = ["쌍바닥","삼중바닥","역헤드앤숄더","N자형","상승추세","쌍봉","삼중천장","헤드앤숄더","역N자형","하락추세","횡보"]
MIRROR = {"쌍바닥":"쌍봉","삼중바닥":"삼중천장","역헤드앤숄더":"헤드앤숄더","N자형":"역N자형","상승추세":"하락추세","횡보":"횡보"}
MIRROR.update({v: k for k, v in list(MIRROR.items())})
UP = {"쌍바닥","삼중바닥","역헤드앤숄더","N자형","상승추세"}
DOWN = {MIRROR[c] for c in UP}
def direction(c): return "상승" if c in UP else ("하락" if c in DOWN else "없음")

# 제로샷용 설명 문장 (영어가 일반적으로 더 잘 동작)
PROMPTS = {
    "쌍바닥": "a candlestick price chart showing a double bottom W pattern",
    "삼중바닥": "a candlestick price chart showing a triple bottom pattern with three equal lows",
    "역헤드앤숄더": "a candlestick price chart showing an inverse head and shoulders pattern",
    "N자형": "a candlestick price chart rising, pulling back, then rising higher in an N shape",
    "상승추세": "a candlestick price chart in a steady uptrend",
    "쌍봉": "a candlestick price chart showing a double top M pattern",
    "삼중천장": "a candlestick price chart showing a triple top pattern with three equal highs",
    "헤드앤숄더": "a candlestick price chart showing a head and shoulders top pattern",
    "역N자형": "a candlestick price chart falling, bouncing, then falling lower in a reversed N shape",
    "하락추세": "a candlestick price chart in a steady downtrend",
    "횡보": "a candlestick price chart moving sideways in a range",
}

def clean(im):
    """빨강·파랑 봉만 남기고 3:2 흰 배경, 450x300으로 맞춤"""
    a = np.array(im.convert("RGB")).astype(int); r, g, b = a[..., 0], a[..., 1], a[..., 2]
    red = (r > 170) & (g < 140) & (b < 140); blue = (b > 150) & (r < 130) & (g < 190)
    c = np.full_like(a, 255); c[red] = a[red]; c[blue] = a[blue]
    ys, xs = np.where(red | blue)
    if len(ys): c = c[max(0, ys.min()-4):ys.max()+5, max(0, xs.min()-2):xs.max()+3]
    im = Image.fromarray(c.astype(np.uint8)); w, h = im.size
    tw, th = max(w, int(1.5*h)), max(h, int(w/1.5))
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
            items.append((f, c, group))
    return items

def as_tensor(e):
    """transformers 4.x는 텐서를, 5.x는 포장된 출력(pooler_output 안에 텐서)을 돌려줌 → 둘 다 처리"""
    return e if isinstance(e, torch.Tensor) else e.pooler_output

@torch.no_grad()
def embed(model, proc, ims, bs=8):
    out = []
    for i in range(0, len(ims), bs):
        x = proc(images=ims[i:i+bs], return_tensors="pt")
        e = as_tensor(model.get_image_features(**x)); out.append(torch.nn.functional.normalize(e, dim=-1))
    return torch.cat(out).numpy()

@torch.no_grad()
def text_embed(model, proc):
    x = proc(text=[PROMPTS[c] for c in CLASSES], padding="max_length", max_length=64, return_tensors="pt")
    e = as_tensor(model.get_text_features(**x)); return torch.nn.functional.normalize(e, dim=-1).numpy()

def main():
    items = load()
    print(f"사진 {len(items)}장:", {c: sum(1 for _, k, _ in items if k == c) for c in CLASSES})
    print("모델 내려받는 중 (처음 한 번, 약 1.5GB)...")
    model = AutoModel.from_pretrained(MODEL_ID).eval(); proc = AutoProcessor.from_pretrained(MODEL_ID)
    ims = [clean(Image.open(f)) for f, _, _ in items]
    y = np.array([c for _, c, _ in items]); groups = [g for _, _, g in items]
    E = embed(model, proc, ims); Ef = embed(model, proc, [flip(im) for im in ims])
    yf = np.array([MIRROR[c] for c in y])

    # 1) 제로샷: 학습 없이 설명 문장과 비교
    T = text_embed(model, proc)
    zs = [CLASSES[i] for i in (E @ T.T).argmax(1)]

    # 2) 임베딩 + 로지스틱 회귀 (그룹 5겹 교차검증, 학습 때만 뒤집은 사진 추가)
    lr = [None] * len(y)
    for tr, te in GroupKFold(n_splits=5).split(E, y, groups):
        Xtr = np.vstack([E[tr], Ef[tr]]); ytr = np.concatenate([y[tr], yf[tr]])
        clf = LogisticRegression(max_iter=2000, C=10).fit(Xtr, ytr)
        for i, p in zip(te, clf.predict(E[te])): lr[i] = p

    res = {}
    for name, pred in (("SigLIP2_제로샷", zs), ("SigLIP2_분류기", lr)):
        acc = float(np.mean([a == b for a, b in zip(pred, y)]))
        dacc = float(np.mean([direction(a) == direction(b) for a, b in zip(pred, y)]))
        res[name] = dict(패턴정답률=round(acc, 3), 방향정답률=round(dacc, 3))
        print(f"{name}: 패턴 {acc:.0%}, 방향 {dacc:.0%}")
    res["예측"] = [dict(file=str(f.relative_to(ROOT)), 정답=c, 제로샷=a, 분류기=b) for (f, c, _), a, b in zip(items, zs, lr)]
    OUT.mkdir(exist_ok=True)
    (OUT / "06_SigLIP2_실험_결과.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", OUT / "06_SigLIP2_실험_결과.json")

if __name__ == "__main__":
    main()
