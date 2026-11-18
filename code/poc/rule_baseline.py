"""
기준선: 첫 실험의 규칙 코드 (AI 없음) — code/실험1/rule.py를 이 PC에서 돌 수 있게 옮긴 것

code/실험1/detect.py는 클라우드 경로에 묶여 있어 그대로 import하면 안 된다(맨 위에서 폴더를 만들고 파일을 읽음).
그래서 그 파일에서 함수 정의(series, zigzag, find)만 꺼내 쓴다. 판정 방법은 rule.py와 같다.
주의: 학습용의 자동 자른 사진은 이 규칙 코드가 정답 이름을 붙인 것이라, 학습용으로 재면 점수가 부풀려진다.
      공정한 비교는 시험용 사진으로만 한다.
"""
import ast
from pathlib import Path
import numpy as np

_DETECT = Path(__file__).resolve().parents[1] / "실험1" / "detect.py"
_ns = {"np": np}
_tree = ast.parse(_DETECT.read_text(encoding="utf-8"))
_funcs = [n for n in _tree.body if isinstance(n, ast.FunctionDef) and n.name in ("series", "zigzag", "find")]
exec(compile(ast.Module(body=_funcs, type_ignores=[]), str(_DETECT), "exec"), _ns)

PRI = {"역헤드앤숄더": 0, "헤드앤숄더": 0, "삼중바닥": 1, "삼중천장": 1, "쌍바닥": 2, "쌍봉": 2, "N자형": 3, "역N자형": 3}

def predict(img):
    """PIL 사진 → 패턴 이름 (rule.py와 같은 방법)"""
    a = np.array(img.convert("RGB")).astype(int); r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = ((r > 170) & (g < 140) & (b < 140)) | ((b > 150) & (r < 130) & (g < 190))
    if not m.any():
        return "횡보"
    xs, v, _, _ = _ns["series"](m); rng = v.max() - v.min(); W = xs.max() - xs.min()
    if rng <= 0 or W <= 0:
        return "횡보"
    best = None
    for th in (0.12, 0.18, 0.25, 0.33):
        piv = _ns["zigzag"](v, th * rng)
        for c, s, e in _ns["find"](piv, v):
            cov = (xs[e] - xs[s]) / W
            if cov < 0.5: continue
            key = (PRI[c], -cov)
            if best is None or key < best[0]: best = (key, c)
    if best: return best[1]
    net = v[-1] - v[0]
    if net > 0.5 * rng: return "상승추세"
    if -net > 0.5 * rng: return "하락추세"
    return "횡보"
