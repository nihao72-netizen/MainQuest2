"""
PoC 공통 전처리 (학습과 실제 판정이 반드시 이 파일의 함수를 같이 쓴다)

- prepare(im): 사진 한 장 → 모델에 넣을 450x300 사진 (빨강·파랑 봉만 남기고 3:2 흰 배경)
- flip(im): 위아래 뒤집기 + 빨강·파랑 맞바꾸기 → 반대 패턴 (학습 때 늘리기용)
- 패턴 이름 ↔ 방향 변환
"""
import numpy as np
from PIL import Image

# ---- 패턴과 방향 ----
CLASSES = ["쌍바닥", "삼중바닥", "역헤드앤숄더", "N자형", "상승추세",
           "쌍봉", "삼중천장", "헤드앤숄더", "역N자형", "하락추세", "횡보"]
MIRROR = {"쌍바닥": "쌍봉", "삼중바닥": "삼중천장", "역헤드앤숄더": "헤드앤숄더",
          "N자형": "역N자형", "상승추세": "하락추세", "횡보": "횡보"}
MIRROR.update({v: k for k, v in list(MIRROR.items())})
UP = {"쌍바닥", "삼중바닥", "역헤드앤숄더", "N자형", "상승추세"}
DOWN = {MIRROR[c] for c in UP}
DIRS = ["상승", "하락", "없음"]
DIR_MIRROR = {"상승": "하락", "하락": "상승", "없음": "없음"}

def direction(pattern):
    """패턴 이름 → 방향 (쌍봉 → 하락 등)"""
    return "상승" if pattern in UP else ("하락" if pattern in DOWN else "없음")

# YOLO 폴더 이름은 영어로 (한글 경로 문제 예방). 모델 안의 이름 ↔ 한글 이름
DIR_EN = {"상승": "up", "하락": "down", "없음": "none"}
CLS_EN = {c: f"c{i:02d}" for i, c in enumerate(CLASSES)}
EN_TO_KO = {**{v: k for k, v in DIR_EN.items()}, **{v: k for k, v in CLS_EN.items()}}

# ---- 사진 전처리 ----
def _masks(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    red = (r > 170) & (g < 140) & (b < 140)
    blue = (b > 150) & (r < 130) & (g < 190)
    return red, blue

def clean(im):
    """빨강·파랑 봉만 남기고 나머지는 흰색, 봉이 있는 범위만 잘라 냄"""
    a = np.array(im.convert("RGB")).astype(int)
    red, blue = _masks(a)
    c = np.full_like(a, 255); c[red] = a[red]; c[blue] = a[blue]
    ys, xs = np.where(red | blue)
    if len(ys):
        c = c[max(0, ys.min() - 4):ys.max() + 5, max(0, xs.min() - 2):xs.max() + 3]
    return Image.fromarray(c.astype(np.uint8))

def to32(im):
    """가로:세로 = 3:2 흰 바탕 가운데에 놓고 450x300으로 맞춤"""
    w, h = im.size
    tw, th = max(w, int(1.5 * h)), max(h, int(w / 1.5))
    cv = Image.new("RGB", (tw, th), "white"); cv.paste(im, ((tw - w) // 2, (th - h) // 2))
    return cv.resize((450, 300), Image.LANCZOS)

def prepare(im):
    """학습 사진이든 실제 화면에서 자른 사진이든 똑같이 이 함수를 거친다"""
    return to32(clean(im))

def has_bars(im, min_pixels=50):
    """사진에 빨강·파랑 봉이 충분히 있는지 (빈 영역 판정 방지)"""
    red, blue = _masks(np.array(im.convert("RGB")).astype(int))
    return int((red | blue).sum()) >= min_pixels

def flip(im):
    """위아래 뒤집고 빨강·파랑 맞바꿈 → 반대 패턴"""
    a = np.array(im.convert("RGB"))[::-1][..., [2, 1, 0]].copy()
    return Image.fromarray(a)
