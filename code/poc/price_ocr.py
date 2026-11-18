"""
실전 기록 1단계: HTS 현재가 칸을 읽는 OCR (윈도우 내장 OCR, 내 PC 안에서만)

- ocr_text(img):  사진 → 글자 (윈도우 내장 OCR)
- parse_price(t): 글자 → 가격 숫자. HTS는 소수점을 쉼표로 씀 (예: '27368,75' = 27368.75)
- read_price(img, prev): 사진 → (가격 또는 None, 읽은 글자, 실패 이유). 숫자 모양·직전 값과의 차이로 검사

윈도우 OCR이 안 되면 숫자 모양 맞추기 방식으로 바꾼다 (사용자 결정).

가격 축에서 현재가 상자 찾기 (사용자 화면에는 고정된 현재가 칸이 없음)
- find_axis_width(): 큰 봉 차트 영역 바로 오른쪽의 초록 가격 축 폭을 잰다
- find_price_boxes(): 가격 축에서 빨강·파랑으로 꽉 찬 상자(현재가 상자 후보)를 찾는다. 글자(LC/HC, 가격 숫자)는 상자가 아니라 빠진다
- read_axis_price(): 차트+가격 축을 한 번에 찍어, 후보가 여럿이면 차트 마지막 봉 높이에 가장 가까운 상자를 골라 OCR
"""
import asyncio, re
import numpy as np
from pathlib import Path
from PIL import Image, ImageOps

_engine = None

def _get_engine():
    global _engine
    if _engine is None:
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.globalization import Language
        eng = None
        for tag in ("en-US", "ko"):
            try:
                lang = Language(tag)
                if OcrEngine.is_language_supported(lang):
                    eng = OcrEngine.try_create_from_language(lang); break
            except Exception:
                pass
        _engine = eng or OcrEngine.try_create_from_user_profile_languages()
        if _engine is None:
            raise RuntimeError("윈도우 OCR 엔진을 만들 수 없습니다 (OCR 언어 팩 없음?)")
    return _engine

async def _ocr_async(img):
    from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode
    from winrt.windows.storage.streams import DataWriter
    rgba = img.convert("RGBA")
    # 윈도우 SoftwareBitmap은 BGRA 순서
    r, g, b, a = rgba.split()
    bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
    w = DataWriter(); w.write_bytes(bgra)
    sb = SoftwareBitmap.create_copy_from_buffer(w.detach_buffer(), BitmapPixelFormat.BGRA8, rgba.width, rgba.height,
                                                BitmapAlphaMode.PREMULTIPLIED)
    res = await _get_engine().recognize_async(sb)
    return res.text

def prepare_for_ocr(img, scale=4, white_text=False):
    """작은 글자는 OCR이 약하므로 키운다.
    white_text=True (색 상자 위 흰 숫자): 흰 픽셀만 검정 글자로 남기고 나머지는 흰 바탕 → 빨강·파랑 바탕 모두 대비가 커짐
    그 밖: 어두운 바탕이면 뒤집어 흰 바탕 검은 글자로"""
    if white_text:
        a = np.asarray(img.convert("RGB")).astype(int)
        whiteness = a.min(2)                                # 흰 글자는 세 색이 모두 큼, 빨강·파랑 바탕은 한 색이 작음
        g = Image.fromarray(np.clip(255 - (whiteness - 90) * 2, 0, 255).astype(np.uint8))
    else:
        g = img.convert("L")
        if sum(g.getdata()) / (g.width * g.height) < 128:      # 바탕이 어두우면 뒤집기
            g = ImageOps.invert(g)
    g = g.resize((g.width * scale, g.height * scale), Image.LANCZOS)
    g = ImageOps.expand(g, border=20, fill=255)             # 가장자리 여백 (글자가 테두리에 붙으면 잘 못 읽음)
    return g.convert("RGB")

def ocr_text(img, scale=4, white_text=False):
    return asyncio.run(_ocr_async(prepare_for_ocr(img, scale, white_text)))

def parse_price(text):
    """'27368,75' / '27368.75' / '27,368.75' / '27368 75'(OCR이 쉼표를 빈칸으로 읽음) → 27368.75.
    소수 부분이 있는 숫자만 가격으로 본다 (소수점 없는 숫자만 있으면 None — 잘못 읽었을 가능성이 큼)"""
    t = text.replace("O", "0").replace("o", "0")
    t = re.sub(r"(\d),(\d{3})[.](\d)", r"\1\2.\3", t)          # 27,368.75 (천 단위 쉼표 + 소수점) → 27368.75
    m = (re.search(r"(?<!\d)(\d{3,6})\s*[.,]\s*(\d{2})(?!\d)", t)
         or re.search(r"(?<!\d)(\d{3,6})\s+(\d{2})(?!\d)", t)
         # 쉼표를 빠뜨린 7자리 (예: '2728950' → 27289.50). 나스닥100 선물은 정수 부분 5자리.
         # read_price의 0.25 단위·직전 값 검사를 함께 통과해야 쓰인다
         or re.search(r"(?<!\d)(\d{5})(\d{2})(?!\d)", t))
    return float(f"{m.group(1)}.{m.group(2)}") if m else None

def read_price(img, prev=None, max_jump=0.03, lo=1000, hi=200000, tick=0.25, white_text=False):
    """돌려주는 값: (가격 또는 None, 읽은 글자, 실패 이유 또는 ''). tick = 호가 단위 (나스닥100 선물 0.25)"""
    try:
        text = ocr_text(img, white_text=white_text)
    except Exception as e:
        return None, "", f"OCR 오류: {e}"
    p = parse_price(text)
    if p is None:
        return None, text, "소수점이 있는 가격 숫자를 찾지 못함"
    if not (lo <= p <= hi):
        return None, text, f"가격 범위를 벗어남 ({p})"
    if tick and abs(p / tick - round(p / tick)) > 1e-6:
        return None, text, f"호가 단위({tick})와 맞지 않음 ({p}) → 잘못 읽은 것 같음"
    if prev and abs(p - prev) / prev > max_jump:
        return None, text, f"직전 값({prev})과 {abs(p - prev) / prev:.1%} 차이 → 잘못 읽은 것 같음"
    return p, text, ""

# ---------------- 가격 축에서 현재가 상자 찾기 ----------------
def _green(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (g > 40) & (g < 140) & (r < 40) & (b < 40)

def find_axis_width(strip, min_green=0.2):
    """차트 영역 바로 오른쪽부터 찍은 사진 → 초록 가격 축 폭(픽셀). 초록이 거의 없는 열이 나오면 거기서 끝"""
    a = np.asarray(strip.convert("RGB")).astype(int)
    frac = _green(a).mean(0)
    w = 0
    while w < len(frac) and frac[w] >= min_green: w += 1
    return w

def find_price_boxes(axis, min_h=15, max_h=45, row_fill=0.35, solid=0.8, gap=3):
    """가격 축 사진 → 색이 꽉 찬 상자 목록 [{y0,y1,x0,x1,색,채움}] (위에서부터).
    - 빨강·파랑이 축 폭의 row_fill 이상인 줄을 이어 붙인다 (숫자가 있는 줄은 0.48–0.66, 상자 위아래 여백 줄은 0.9 이상 — 실제 화면에서 잼)
    - gap줄 이하로 끊긴 것은 이어 본다
    - 그중 solid 이상인 '꽉 찬 줄'이 있어야 상자로 인정 → LC/HC 같은 색 글자, 가격 숫자는 빠진다"""
    a = np.asarray(axis.convert("RGB")).astype(int); r, g, b = a[..., 0], a[..., 1], a[..., 2]
    red = (r > 150) & (g < 110) & (b < 110)
    blue = (b > 150) & (r < 110) & (g < 180)
    out = []
    for name, m in (("빨강", red), ("파랑", blue)):
        frac = m.mean(1)
        on = np.where(frac >= row_fill)[0]
        runs = []
        for y in on:
            if runs and y - runs[-1][1] <= gap + 1: runs[-1][1] = y
            else: runs.append([y, y])
        for y0, y1 in runs:
            if not (min_h <= y1 - y0 + 1 <= max_h) or frac[y0:y1 + 1].max() < solid:
                continue
            cols = np.where(m[y0:y1 + 1].mean(0) > 0.5)[0]
            if not len(cols): continue
            out.append(dict(y0=int(y0), y1=int(y1), x0=int(cols.min()), x1=int(cols.max()), 색=name,
                            채움=float(m[y0:y1 + 1, cols.min():cols.max() + 1].mean())))
    return sorted(out, key=lambda d: d["y0"])

def last_bar_yrange(chart, bar_px=11):
    """차트 사진에서 마지막 봉(가장 오른쪽 봉)의 위·아래 y. 봉이 없으면 None"""
    a = np.asarray(chart.convert("RGB")).astype(int); r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = ((r > 170) & (g < 140) & (b < 140)) | ((b > 150) & (r < 130) & (g < 190))
    xs = np.where(m.any(0))[0]
    if not len(xs): return None
    x1 = xs.max(); x0 = max(0, x1 - int(round(bar_px)) + 1)
    ys = np.where(m[:, x0:x1 + 1].any(1))[0]
    return int(ys.min()), int(ys.max())

def pick_price_box(boxes, bar_y=None, tol=25):
    """현재가 상자 고르기: 상자 가운데가 마지막 봉의 높이(bar_y, 위·아래 tol px 여유) 안에 있는 것만 후보.
    여럿이면 가장 가까운 것. 하나도 없으면 고르지 않는다 (다른 상자를 현재가로 잘못 읽지 않게).
    예: 마우스가 차트 위에 있으면 십자선 가격 상자(파랑, 0.25 단위가 아닌 값)가 생긴다 — 2026-11-18 실제 화면에서 봄"""
    if not boxes: return None, "색이 꽉 찬 상자를 찾지 못함"
    if bar_y is None: return None, f"상자 {len(boxes)}개인데 차트의 마지막 봉을 찾지 못해 고를 수 없음"
    lo, hi = bar_y
    def dist(bx):
        c = (bx["y0"] + bx["y1"]) / 2
        return 0 if lo <= c <= hi else min(abs(c - lo), abs(c - hi))
    near = [b for b in boxes if dist(b) <= tol]
    if not near:
        return None, (f"상자 {len(boxes)}개가 모두 마지막 봉 높이({lo}–{hi})에서 멀어 현재가 상자가 아님 "
                      "(마우스가 차트 위에 있으면 십자선 가격 상자가 생길 수 있음)")
    best = min(near, key=dist)
    return best, f"상자 {len(boxes)}개 중 마지막 봉 높이 안의 것 (거리 {dist(best):.0f}px)"

def read_axis_price(chart_region, axis_width, bar_px=11, prev=None, img=None, save_path=None):
    """차트 + 가격 축을 한 번에 찍어 현재가를 읽는다. img를 주면 화면 대신 그 사진(차트+축이 붙은 사진)을 씀.
    돌려주는 값: dict(가격, 글자, 실패이유, 상자, 상자수, 고른이유, 상자사진)"""
    if img is None:
        import capture as C
        img = C.grab_region(dict(left=chart_region["left"], top=chart_region["top"],
                                 width=chart_region["width"] + axis_width, height=chart_region["height"]))
    W = chart_region["width"]
    chart, axis = img.crop((0, 0, W, img.height)), img.crop((W, 0, W + axis_width, img.height))
    boxes = find_price_boxes(axis)
    box, why_pick = pick_price_box(boxes, last_bar_yrange(chart, bar_px))
    res = dict(가격=None, 글자="", 실패이유="", 상자=box, 상자수=len(boxes), 고른이유=why_pick, 상자사진=None)
    if box is None:
        res["실패이유"] = why_pick; return res
    # 상자 줄만 정확히 자름 (바로 아래·위의 가격 눈금 숫자가 섞이지 않게)
    crop = axis.crop((box["x0"], box["y0"], box["x1"] + 1, box["y1"] + 1))
    if save_path:
        save_path = Path(save_path); save_path.parent.mkdir(parents=True, exist_ok=True); crop.save(save_path)
        res["상자사진"] = str(save_path)
    res["가격"], res["글자"], res["실패이유"] = read_price(crop, prev, white_text=True)
    return res

# ---------------- 차트 위 고정 현재가 칸 (예: '27164.25▼') ----------------
def _glyphs(img):
    """글자 덩어리(세로로 빈 열로 나뉜 것) 목록과 글자 픽셀 지도. 파란 글자·진한 글자를 글자로 봄"""
    a = np.asarray(img.convert("RGB")).astype(int)
    ink = ((a.max(2) - a.min(2)) > 60) | (a.max(2) < 110)
    cols = np.where(ink.any(0))[0]; gs = []
    for x in cols:
        if gs and x - gs[-1][1] <= 1: gs[-1][1] = x
        else: gs.append([x, x])
    out = []
    for s, e in gs:
        ys = np.where(ink[:, s:e + 1].any(1))[0]
        out.append(dict(s=int(s), e=int(e), h=int(ys.max() - ys.min() + 1)))
    return ink, out

def read_field(img, prev=None, gap=10, scale=4, tick=0.25):
    """고정 현재가 칸 읽기. 이 PC의 OCR(한국어 엔진)은 붙어 있는 '71'을 한글 '기'로, 점을 '4'로 읽는 일이 있어서
    점(키가 작은 덩어리)과 끝의 화살표(▼▲)는 모양으로 골라내고, 숫자 7개만 사이를 벌려 OCR → 'ddddd.dd'로 조립.
    돌려주는 값: (가격 또는 None, 읽은 글자, 실패 이유)"""
    ink, gs = _glyphs(img)
    if not gs: return None, "", "글자를 찾지 못함"
    H = max(g["h"] for g in gs)
    digits = [g for g in gs if g["h"] >= 0.5 * H]
    if len(digits) == 8: digits = digits[:7]                     # 마지막 = 화살표
    if len(digits) != 7: return None, "", f"숫자 덩어리가 {len(digits)}개 (7개여야 함)"
    base = Image.fromarray(np.where(ink, 0, 255).astype(np.uint8))
    out = Image.new("L", (sum(g["e"] - g["s"] + 1 for g in digits) + gap * 8, ink.shape[0]), 255); x = gap
    for g in digits:
        out.paste(base.crop((g["s"], 0, g["e"] + 1, ink.shape[0])), (x, 0)); x += g["e"] - g["s"] + 1 + gap
    out = ImageOps.expand(out.resize((out.width * scale, out.height * scale), Image.LANCZOS), border=20, fill=255).convert("RGB")
    try:
        text = asyncio.run(_ocr_async(out))
    except Exception as e:
        return None, "", f"OCR 오류: {e}"
    d = "".join(ch for ch in text if ch.isdigit())
    if len(d) != 7: return None, text, f"숫자 {len(d)}개를 읽음 (7개여야 함)"
    p = float(d[:5] + "." + d[5:])
    if tick and abs(p / tick - round(p / tick)) > 1e-6: return None, text, f"호가 단위({tick})와 맞지 않음 ({p})"
    if prev and abs(p - prev) / prev > 0.03: return None, text, f"직전 값({prev})과 너무 다름 ({p})"
    return p, text, ""

DEFAULT_FIELD = {"dx": 14, "dy": -37, "w": 96, "h": 24}   # 큰 봉 그래프 영역 왼쪽 위 기준 (2026-11-18 모니터 2에서 잼)

def read_price_both(chart_region, field=None, axis_width=117, bar_px=11, prev=None, img=None, save_path=None, agree=5.0,
                    max_jump=0.03):
    """차트 위 고정 현재가 칸 + 가격 축 현재가 상자를 '한 장으로' 찍어 같은 순간의 두 값을 비교.
    - 둘 다 읽히고 agree 포인트 이내 → 믿음 (출처 '두 곳 일치', 값은 현재가 칸). 같은 사진에서도 HTS가 두 칸을 조금 다른
      순간에 그려 1–2포인트 다를 수 있음(2026-11-18 실제 화면). 잘못 읽으면 수천 포인트 차이이거나 0.25 단위 검사에 걸림
    - 한 곳만 읽힘 → **기준값(prev)이 있고 3% 이내일 때만** 그 값 (출처 '현재가 칸만' / '가격 축만').
      기준값이 없으면 믿지 않는다. 2026-11-18 실제 사고: 현재가 칸이 27332를 22332로 잘못 읽었는데, 그때 가격 축을
      못 읽었고 기준값을 넘겨주지 않아 3% 검사가 동작하지 않아 그대로 기록됨. 또 과거로 넘긴 차트에서는 가격 축 상자가
      과거 가격(13554 등)을 보여 '가격 축만'으로 기록됨
    - 둘 다 읽혔는데 다름 → 실패 (잘못 읽은 것)
    - 두 곳이 일치하면 기준값과 상관없이 믿는다 (시장이 실제로 크게 움직였을 때 막히지 않게)
    돌려주는 값: dict(가격, 출처, 칸값, 칸글자, 칸실패, 축값, 축글자, 축실패, 실패이유, 사진)"""
    f = dict(DEFAULT_FIELD, **(field or {}))
    top_pad = max(0, -f["dy"])
    if img is None:
        import capture as C
        img = C.grab_region(dict(left=chart_region["left"], top=chart_region["top"] - top_pad,
                                 width=chart_region["width"] + axis_width, height=chart_region["height"] + top_pad))
    fld = img.crop((f["dx"], top_pad + f["dy"], f["dx"] + f["w"], top_pad + f["dy"] + f["h"]))
    chart_axis = img.crop((0, top_pad, img.width, img.height))
    fp, ft, fw = read_field(fld, None)                       # 기준값 검사는 아래에서 한 곳만 읽혔을 때만
    ax = read_axis_price(chart_region, axis_width, bar_px, None, img=chart_axis)
    ap = ax["가격"]
    res = dict(가격=None, 출처="", 칸값=fp, 칸글자=ft, 칸실패=fw, 축값=ap, 축글자=ax["글자"], 축실패=ax["실패이유"],
               실패이유="", 사진=None, 기준값=prev)
    def single(p, name):
        if not prev:
            res["실패이유"] = f"{name}만 읽혔는데 비교할 기준값이 없어 믿지 않음 ({p})"
        elif abs(p - prev) / prev > max_jump:
            res["실패이유"] = f"{name}만 읽혔는데 기준값 {prev}와 {abs(p - prev) / prev:.1%} 차이 → 잘못 읽은 것 같음 ({p})"
        else:
            res.update(가격=p, 출처=f"{name}만")
    if fp is not None and ap is not None:
        if abs(fp - ap) <= agree: res.update(가격=fp, 출처="두 곳 일치")
        else: res["실패이유"] = f"두 곳 값이 다름 (현재가 칸 {fp}, 가격 축 {ap})"
    elif fp is not None: single(fp, "현재가 칸")
    elif ap is not None: single(ap, "가격 축")
    else: res["실패이유"] = f"둘 다 못 읽음 (현재가 칸: {fw} / 가격 축: {ax['실패이유']})"
    if save_path:
        parts = [fld]
        if ax["상자"]:
            b = ax["상자"]; parts.append(chart_axis.crop((chart_region["width"] + b["x0"], b["y0"], chart_region["width"] + b["x1"] + 1, b["y1"] + 1)))
        W = sum(p.width for p in parts) + 10 * (len(parts) - 1); Hh = max(p.height for p in parts)
        sheet = Image.new("RGB", (W, Hh), "white"); x = 0
        for p in parts: sheet.paste(p, (x, 0)); x += p.width + 10
        save_path = Path(save_path); save_path.parent.mkdir(parents=True, exist_ok=True); sheet.save(save_path)
        res["사진"] = str(save_path)
    return res

def read_price_retry(chart_region, field=None, axis_width=117, bar_px=11, prev=None, save_path=None, tries=3, wait=1.0):
    """read_price_both를 실패하면 wait초 간격으로 tries번까지 다시. 마지막 결과에 시도 횟수를 붙여 돌려줌"""
    import time
    for k in range(tries):
        res = read_price_both(chart_region, field, axis_width, bar_px, prev, save_path=save_path)
        res["시도"] = k + 1
        if res["가격"] is not None: return res
        if k < tries - 1: time.sleep(wait)
    return res
