"""
PoC 4단계: 판정 결과를 사람이 보고 나중에 다시 분석할 수 있게 남기는 함수들

- console_line(): 콘솔 한 줄 요약
- csv_rows():     CSV 줄 (창 하나 = 한 줄). 점수는 반올림하지 않고 그대로, 모델 파일·설정값도 함께
- append_csv():   CSV에 덧붙이기 (열 구성이 바뀌면 새 파일로)
- annotate():     확인용 이미지 (차트 영역 + 창 위치 + 창별 모델 입력 사진 + 결과 글자)
"""
import csv, hashlib, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

import preprocess as P
import rules as R

# ---------- 모델·설정 이름표 ----------
def model_tag(models_dir, name):
    """예: 'dir3.pt|학습 2026-11-17T21:33:43|md5 1a2b3c4d' → 모델을 다시 학습하면 달라진다"""
    md = Path(models_dir)
    pt, js = md / f"{name}.pt", md / f"{name}.json"
    h = hashlib.md5(pt.read_bytes()).hexdigest()[:8] if pt.exists() else "없음"
    when = json.loads(js.read_text(encoding="utf-8")).get("학습날짜", "?") if js.exists() else "?"
    return f"{pt.name}|학습 {when}|md5 {h}"

# ---------- 콘솔 ----------
def console_line(when, res, chart=None):
    head = f"{when:%Y-%m-%d %H:%M:%S} | " + (f"[{chart}] " if chart else "") + f"{res['판정']}" + (f"({res['방향']})" if res["판정"] == R.ALERT else "")
    head += f" [{res.get('근거', '')}]"
    main = None
    if res["windows"]:
        main_bars = res.get("기준창")
        main = min(res["windows"], key=lambda w: abs(w["bars"] - main_bars)) if main_bars else res["windows"][0]
        head += (f" | {main['bars']}봉 창: 3분류 {main['dir3']} 점수 {main['dir3_점수'][main['dir3']]}"
                 f" | 11분류 참고: {main['cls11']} 모양과 비슷 ({main['cls11_방향']}) 점수 {main['cls11_점수'][main['cls11']]}")
        others = [f"{w['bars']}봉 {w['판정'][:2]}" + (f"({w['방향']})" if w["판정"] == R.ALERT else "")
                  for w in res["windows"] if w is not main]
        if others: head += " | 다른 창: " + ", ".join(others)
    for w in res.get("경고", []):
        head += f" | ⚠ {w}"
    return head

# ---------- CSV ----------
DIR_COLS = [f"dir3_점수_{d}" for d in P.DIRS]
CLS_COLS = [f"cls11_점수_{c}" for c in P.CLASSES]
COLUMNS = (["시각", "실행ID", "차트", "최종판정", "최종방향", "근거", "경고",
            "창_봉수", "창_px", "창_x0", "창_x1", "봉수_충분", "창판정", "창방향",
            "dir3", *DIR_COLS, "cls11", "cls11_방향", *CLS_COLS,
            "모델_dir3", "모델_cls11",
            "설정_window_bars", "설정_rule", "설정_min_dir3_score", "설정_window_combine", "설정_main_bars",
            "설정_bar_px", "설정_bar_px_warn_diff",
            "봉간격_측정px", "회색비율_전체", "회색비율_칸2위", "설정_region", "입력", "캡처파일", "확인이미지"])

def csv_rows(when, run_id, res, s, region, model_tags, files, chart=""):
    base = {"시각": when.isoformat(timespec="seconds"), "실행ID": run_id, "차트": chart,
            "최종판정": res["판정"], "최종방향": res["방향"] or "", "근거": res.get("근거", ""),
            "경고": " / ".join(res.get("경고", [])),
            "모델_dir3": model_tags["dir3"], "모델_cls11": model_tags["cls11"],
            "설정_window_bars": json.dumps(s["window_bars"]), "설정_rule": s["rule"], "설정_min_dir3_score": s["min_dir3_score"],
            "설정_window_combine": s["window_combine"], "설정_main_bars": s["main_bars"],
            "설정_bar_px": s["bar_px"], "설정_bar_px_warn_diff": s["bar_px_warn_diff"],
            "봉간격_측정px": ("측정 안 함(봉이 붙음)" if (res["layout"] or {}).get("봉이_붙음")
                            else (res["layout"] or {}).get("봉간격_px", "")),
            "회색비율_전체": repr(res.get("차트확인", {}).get("회색비율_전체", "")),
            "회색비율_칸2위": repr(res.get("차트확인", {}).get("회색비율_칸2위", "")),
            "설정_region": json.dumps(region, ensure_ascii=False), **files}
    if not res["windows"]:
        return [base]
    rows = []
    for w in res["windows"]:
        r = dict(base)
        r.update({"창_봉수": w["bars"], "창_px": w["폭_px"], "창_x0": w["x0"], "창_x1": w["x1"], "봉수_충분": w["봉수_충분"],
                  "창판정": w["판정"], "창방향": w["방향"] or "", "dir3": w["dir3"], "cls11": w["cls11"], "cls11_방향": w["cls11_방향"]})
        r.update({f"dir3_점수_{k}": repr(v) for k, v in w["dir3_점수"].items()})      # repr = 반올림 없이 전체 자릿수
        r.update({f"cls11_점수_{k}": repr(v) for k, v in w["cls11_점수"].items()})
        rows.append(r)
    return rows

def append_rows(path, columns, rows):
    """CSV에 덧붙이기. 열 구성이 같으면 덧붙이고, 다르면(코드가 바뀜) _v2, _v3… 새 파일. 엑셀용 utf-8-sig"""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with open(path, encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f), None)
        if header != columns:
            k = 2
            while True:
                cand = path.with_name(f"{path.stem}_v{k}{path.suffix}")
                if not cand.exists(): break
                with open(cand, encoding="utf-8-sig", newline="") as f:
                    if next(csv.reader(f), None) == columns: break
                k += 1
            path = cand
    new = not path.exists()
    with open(path, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=columns)
        if new: wr.writeheader()
        for r in rows: wr.writerow(r)
    return path

def append_csv(path, rows):
    """판정기록 CSV에 덧붙이기 (열 구성이 바뀌면 열 구성이 같은 _vN 파일에 이어 씀)"""
    return append_rows(path, COLUMNS, rows)

# ---------- 확인용 이미지 ----------
def _font(size):
    for p in ("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/gulim.ttc"):
        try: return ImageFont.truetype(p, size)
        except OSError: pass
    return ImageFont.load_default()

def _color(judge, d):
    if judge == R.ALERT: return (210, 30, 30) if d == "상승" else (30, 70, 220)
    return (130, 130, 130) if judge == R.UNSURE else (40, 40, 40)

def annotate(region_img, res, when, width=1800, chart=None):
    """위: 차트 영역(줄임) + 창 시작 위치 / 아래: 창별 모델 입력 사진(450x300) + 판정 글자"""
    f_big, f_small = _font(28), _font(18)
    sc = width / region_img.width
    top = region_img.resize((width, max(1, int(region_img.height * sc))))
    n = max(1, len(res["windows"]))
    cell_w = max(450, width // n)
    H = 50 + top.height + 20 + 300 + 110
    canvas = Image.new("RGB", (max(width, cell_w * n), H), "white")
    d = ImageDraw.Draw(canvas)
    title = f"{when:%Y-%m-%d %H:%M:%S}   " + (f"[{chart}]  " if chart else "") + f"최종: {res['판정']}" + (f" ({res['방향']})" if res["판정"] == R.ALERT else "")
    title += f"   [{res.get('근거', '')}]"
    d.text((10, 10), title, fill=_color(res["판정"], res["방향"]), font=f_big)
    canvas.paste(top, (0, 50))
    for k, w in enumerate(res["windows"]):
        c = _color(w["판정"], w["방향"]); x = int(w["x0"] * sc)
        d.line((x, 50, x, 50 + top.height), fill=c, width=3)
        d.text((x + 4, 52 + 22 * k), f"← {w['bars']}봉 창 시작", fill=c, font=f_small)
        ox, oy = k * cell_w, 50 + top.height + 20
        canvas.paste(w["img"], (ox, oy)); d.rectangle((ox, oy, ox + 449, oy + 299), outline=c, width=3)
        lines = [f"{w['bars']}봉 창: {w['판정']}" + (f" ({w['방향']})" if w["판정"] == R.ALERT else ""),
                 f"3분류 {w['dir3']}  점수 {w['dir3_점수'][w['dir3']]:.4f}",
                 f"11분류 {w['cls11']}({w['cls11_방향']})  점수 {w['cls11_점수'][w['cls11']]:.4f}"]
        for j, t in enumerate(lines):
            d.text((ox + 5, oy + 305 + 24 * j), t, fill=c if j == 0 else (0, 0, 0), font=f_small)
    foot = "점수는 소수 4자리로 표시 (전체 값은 CSV). 점수는 확률이 아니다. 주문은 사람이 한다."
    for w in res.get("경고", []): foot = f"[경고] {w}   " + foot      # ⚠ 기호는 맑은 고딕에 없어 글자로
    d.text((10, H - 28), foot, fill=(180, 0, 0) if res.get("경고") else (90, 90, 90), font=f_small)
    return canvas
