"""
PoC 3단계: 판정 창 자르기 + 두 모델 판정 + 알림 규칙 적용

학습 사진은 '패턴 하나를 잘라 낸 사진'이었으므로, 실제 화면에서는
'오른쪽 끝(마지막 봉 = 지금)에서 끝나는 최근 구간'을 여러 폭(예: 최근 100·150·200봉)으로 잘라 각각 판정한다.

- bar_layout():  차트에서 봉이 있는 범위와 봉 하나의 간격(픽셀)을 잰다
- cut_windows(): 마지막 봉에서 끝나는 N봉 너비의 창을 자른다 (전처리는 preprocess.prepare — 학습과 같은 함수)
- Judge:         models/의 두 모델로 판정, 모든 클래스 점수를 반올림 없이 돌려준다
- judge_region(): 위를 묶어 창별 판정 + 최종 판정

시험 실행 (기록은 남기지 않음):
  python code/poc/judge.py --image logs/setup/<시각>_영역.png
  python code/poc/judge.py --image data/원본캡처/원본01.png --full     (축이 포함된 사진이면 --full)
  python code/poc/judge.py --live                                        (config의 차트 영역을 지금 캡처)
"""
import argparse, json, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preprocess as P
import rules as R
import capture as C

DEFAULTS = {"window_bars": [100, 150, 200], "bar_px": 9, "bar_px_warn_diff": 2, "rule": "agree", "min_dir3_score": 0.0,
            "window_combine": "main", "main_bars": 150, "models_dir": "models", "right_pad_px": 3,
            "chart_gray_max_total": 0.01, "chart_gray_max_tile": 0.04}
ZOOM_WARN = "차트 확대 비율이 바뀐 것 같다"
COVER_WARN = "차트가 다른 창에 가려진 것 같다"

# ---------- 차트인지 확인 ----------
def chart_check(region_img, s, gx=8, gy=4):
    """차트 영역에 회색·검정(글자, 창 테두리, 메뉴)이 많으면 다른 창이 가린 것으로 본다.
    진짜 차트: 전체 0.0006–0.0026, 두 번째로 많은 칸 0.0044–0.0209 / 다른 창에 가려진 화면: 0.0289, 0.0741 (진행기록 12번)
    왼쪽 위 시·고·저·종 글자 칸은 뺀다. 칸 하나만 높은 것(안내 상자 등)은 봐준다(두 번째로 많은 칸을 봄)."""
    a = np.asarray(region_img.convert("RGB")).astype(int); H, W = a.shape[:2]
    mx, mn = a.max(2), a.min(2)
    gray = (mx - mn < 40) & (mx < 200)
    gray[:70, :700] = False
    total = float(gray.mean())
    tiles = sorted(float(gray[y * H // gy:(y + 1) * H // gy, x * W // gx:(x + 1) * W // gx].mean())
                   for y in range(gy) for x in range(gx))
    tile2 = tiles[-2]
    ok = total <= s["chart_gray_max_total"] and tile2 <= s["chart_gray_max_tile"]
    return ok, dict(회색비율_전체=total, 회색비율_칸2위=tile2)

def settings(cfg, chart=None):
    """공통 설정 + (chart를 주면) 그 차트의 bar_px가 있으면 그것으로 덮어씀"""
    s = dict(DEFAULTS); s.update({k: cfg[k] for k in DEFAULTS if k in cfg})
    if chart and cfg.get("charts", {}).get(chart, {}).get("bar_px"):
        s["bar_px"] = cfg["charts"][chart]["bar_px"]
    return s

# ---------- 봉 간격 재기 ----------
TOUCH_COVER = 0.9      # 봉이 있는 세로줄 비율이 이보다 크면 봉끼리 붙어 있는 것 (빈틈 있는 차트 0.65–0.78, 붙은 차트 0.98)
DENSE_BAR_PX = 5       # 설정한 봉 간격이 이보다 작으면 "원래 봉이 붙어 보이는 빽빽한 차트"로 본다

def bar_layout(region_img):
    """봉이 있는 x 범위와 봉 간격. 빈 세로줄로 나뉜 덩어리 하나 = 봉 하나 (진행기록 12: 원본캡처·실제 화면에서 확인)
    봉끼리 붙어 있으면(빈틈이 거의 없으면) 덩어리 하나에 봉 여러 개가 들어가므로 간격을 재지 않는다(None)."""
    a = np.asarray(region_img.convert("RGB")).astype(int)
    red, blue = P._masks(a)
    has = (red | blue).any(0)
    xs = np.where(has)[0]
    if len(xs) == 0:
        return None
    cover = float(has[xs.min():xs.max() + 1].mean())
    d = np.diff(np.concatenate([[0], has.astype(np.int8), [0]]))
    starts = np.where(d == 1)[0]
    touching = cover > TOUCH_COVER
    pitch = float(np.median(np.diff(starts))) if len(starts) > 2 and not touching else None
    return dict(first=int(xs.min()), last=int(xs.max()), 덩어리수=int(len(starts)), 봉간격_px=pitch,
                봉있는세로줄비율=cover, 봉이_붙음=touching)

def zoom_warning(layout, s):
    """확대 비율이 바뀐 것 같은지. 설정 bar_px와 측정값 비교 (봉이 붙어 있는 차트도 처리)"""
    want, measured = s["bar_px"], layout["봉간격_px"]
    if not want:
        return None
    if measured is None:   # 봉이 붙어 있어 잴 수 없음
        if want >= DENSE_BAR_PX:
            return f"{ZOOM_WARN} (봉이 서로 붙어 보임 → 축소된 것 같음, 설정 {want}px)"
        return None        # 원래 빽빽한 차트: 정상
    if abs(measured - want) >= s["bar_px_warn_diff"]:
        return f"{ZOOM_WARN} (측정 {measured}px, 설정 {want}px)"
    return None

# ---------- 창 자르기 ----------
def cut_windows(region_img, window_bars, bar_px, layout, right_pad=3):
    W, H = region_img.size
    x1 = min(W, layout["last"] + 1 + right_pad)
    out = []
    for n in window_bars:
        want = int(round(n * bar_px))
        x0 = x1 - want
        enough = x0 >= layout["first"]
        x0 = max(layout["first"], x0)
        raw = region_img.crop((x0, 0, x1, H))
        out.append(dict(bars=int(n), x0=int(x0), x1=int(x1), 폭_px=int(x1 - x0), 봉수_충분=bool(enough),
                        raw=raw, img=P.prepare(raw)))
    return out

# ---------- 모델 ----------
class Judge:
    def __init__(self, models_dir):
        from ultralytics import YOLO
        md = Path(models_dir)
        if not md.is_absolute(): md = C.ROOT / md
        self.m3, self.m11 = YOLO(str(md / "dir3.pt")), YOLO(str(md / "cls11.pt"))
        self.info = {k: json.loads((md / f"{k}.json").read_text(encoding="utf-8")) for k in ("dir3", "cls11")}

    @staticmethod
    def _scores(model, img):
        r = model.predict(np.array(img)[..., ::-1], imgsz=224, device="cpu", verbose=False)[0]  # BGR 배열
        sc = {P.EN_TO_KO[model.names[i]]: float(s) for i, s in enumerate(r.probs.data.tolist())}   # 반올림 없음
        return max(sc, key=sc.get), sc

    def __call__(self, img):
        d3, s3 = self._scores(self.m3, img)
        c11, s11 = self._scores(self.m11, img)
        return dict(dir3=d3, dir3_점수=s3, cls11=c11, cls11_점수=s11, cls11_방향=P.direction(c11))

# ---------- 묶기 ----------
def judge_region(region_img, judge, s):
    ok, chk = chart_check(region_img, s)
    if not ok:
        return dict(layout=None, windows=[], 판정=R.NOT_CHART, 방향=None, 근거="차트가 아님 → 판정 안 함",
                    규칙=s["rule"], 창묶기=s["window_combine"], 차트확인=chk, 차트아님=True,
                    경고=[f"{COVER_WARN} (회색·검정 비율 전체 {chk['회색비율_전체']:.4f}, 칸 2위 {chk['회색비율_칸2위']:.4f}) "
                          "— 판정하지 않고 사진도 저장하지 않음"])
    layout = bar_layout(region_img)
    if layout is None or not P.has_bars(region_img):
        return dict(layout=layout, windows=[], 판정=R.NONE, 방향="없음", 근거="차트에서 봉을 찾지 못함",
                    규칙=s["rule"], 창묶기=s["window_combine"], 경고=["차트에서 봉을 찾지 못함 (HTS 창이 가려졌거나 위치가 바뀜?)"])
    bar_px = s["bar_px"] or layout["봉간격_px"]
    layout["사용한_봉간격_px"] = bar_px; layout["봉간격_출처"] = "config" if s["bar_px"] else "자동"
    warnings = []
    zw = zoom_warning(layout, s)
    if zw: warnings.append(zw)
    wins = cut_windows(region_img, s["window_bars"], bar_px, layout, s["right_pad_px"])
    for w in wins:
        w.update(judge(w["img"]))
        w["판정"], w["방향"] = R.decide(w["dir3"], w["cls11_방향"], s["rule"],
                                       w["dir3_점수"][w["dir3"]], s["min_dir3_score"])
    final, d, why = R.combine(wins, s["window_combine"], s["main_bars"])
    return dict(layout=layout, windows=wins, 판정=final, 방향=d, 근거=why, 규칙=s["rule"], 창묶기=s["window_combine"],
                경고=warnings, 차트확인=chk, 차트아님=False)

def describe(res):
    """사람이 읽는 여러 줄 요약"""
    L = res["layout"]
    lines = [f"최종: {res['판정']}" + (f" ({res['방향']})" if res["방향"] and res["판정"] == R.ALERT else "")
             + f"  [{res.get('근거', '')}]"]
    lines += [f"  ⚠ 경고: {w}" for w in res.get("경고", [])]
    if L:
        meas = "봉이 붙어 있어 측정 안 함" if L.get("봉이_붙음") else f"측정 {L.get('봉간격_px')}px"
        lines.append(f"  봉 간격 {L.get('사용한_봉간격_px')}px ({L.get('봉간격_출처')}, {meas}), "
                     f"봉 있는 x {L['first']}..{L['last']}, 덩어리 {L['덩어리수']}개")
    for w in res["windows"]:
        top11 = sorted(w["cls11_점수"].items(), key=lambda t: -t[1])[:2]
        lines.append(f"  {w['bars']:>3}봉 창({w['폭_px']}px{'' if w['봉수_충분'] else ', 봉 부족'}): {w['판정']:<9} | "
                     f"3분류 {w['dir3']} 점수 {w['dir3_점수'][w['dir3']]} | "
                     f"11분류 {w['cls11']}({w['cls11_방향']}) 점수 {w['cls11_점수'][w['cls11']]} | 2위 {top11[1][0]} {top11[1][1]}")
    return "\n".join(lines)

def main():
    ap = argparse.ArgumentParser(description="판정 시험 (기록은 남기지 않음)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--image", type=Path, help="차트 영역 사진")
    g.add_argument("--live", action="store_true", help="config의 차트 영역을 지금 캡처")
    ap.add_argument("--chart", type=C.chart_name, default=C.BIG, help="--live 로 판정할 차트: 큰봉(화면 위, 기본) 또는 작은봉(화면 아래)")
    ap.add_argument("--full", action="store_true", help="--image가 축까지 포함된 사진이면 그래프 영역을 먼저 찾음")
    ap.add_argument("--bars", type=int, nargs="+", help="창 폭(봉 수) 목록. 기본: config의 window_bars")
    ap.add_argument("--save-dir", type=Path, help="잘린 창 사진을 여기에 저장 (확인용)")
    args = ap.parse_args()
    cfg = C.load_config(); s = settings(cfg, args.chart)
    if args.bars: s["window_bars"] = args.bars
    if args.live:
        print("차트:", args.chart)
        img = C.grab_region(C.chart_region(cfg, args.chart))
    else:
        img = P.Image.open(args.image).convert("RGB")
        if args.full:
            import setup_region as S
            ar = S.find_plot_areas(img)[0]; img = img.crop((ar["left"], ar["top"], ar["right"], ar["bottom"]))
    res = judge_region(img, Judge(s["models_dir"]), s)
    print(describe(res))
    if args.save_dir:
        args.save_dir.mkdir(parents=True, exist_ok=True)
        for w in res["windows"]:
            w["raw"].save(args.save_dir / f"창{w['bars']}_raw.png"); w["img"].save(args.save_dir / f"창{w['bars']}_모델입력.png")

if __name__ == "__main__":
    main()
