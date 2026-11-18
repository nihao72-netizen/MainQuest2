"""
PoC 2단계: 차트 영역 좌표 도우미 (처음 한 번, 또는 HTS 창 위치를 바꿨을 때 실행)

하는 일
1. 화면 전체를 메모리로 캡처 (또는 --image 로 준 사진을 사용)
2. 초록 날짜 축(가로 띠)과 초록 가격 축(세로 띠)을 찾아, 그 둘이 감싸는 흰 그래프 영역을 추정
   - 날짜 축이 여러 개면 가장 위의 것 = 위쪽 큰 봉 차트 (--pick 으로 다른 것 선택 가능)
3. 찾은 영역을 config.json의 region에 저장
4. 확인용 사진 저장: logs/setup/<시각>_영역.png (차트 영역만)
   화면 전체 사진은 config의 save_full_screenshot이 true일 때만 저장 (기본 false: 계좌·주문 정보 보호)

실행:  python code/poc/setup_region.py                 (지금 화면에서 찾기)
       python code/poc/setup_region.py --delay 5       (5초 뒤 캡처: 그사이 HTS 창을 앞으로)
       python code/poc/setup_region.py --monitor 2 --delay 5   (HTS가 두 번째 모니터에 있을 때)
       python code/poc/setup_region.py --image data/원본캡처/원본01.png --no-write   (사진으로 시험)
"""
import argparse, sys, time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture as C

def green_mask(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (g > 40) & (g < 140) & (r < 40) & (b < 40)

def _runs(flags):
    """True가 이어지는 구간 [(시작, 끝)] (끝 포함)"""
    d = np.diff(np.concatenate([[0], np.asarray(flags, np.int8), [0]]))
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0] - 1
    return list(zip(starts.tolist(), ends.tolist()))

def _merge(runs, max_gap):
    """틈이 max_gap 이하인 구간끼리 이어 붙임 (날짜 축의 흰 글자 때문에 초록이 끊기는 것 보정)"""
    out = []
    for s, e in runs:
        if out and s - out[-1][1] - 1 <= max_gap: out[-1] = (out[-1][0], e)
        else: out.append((s, e))
    return out

def find_plot_areas(img, min_width_frac=0.3, min_white=0.5, max_gap=60, max_border=15):
    """초록 날짜 축 위의 흰 그래프 영역 후보들을 위에서부터 돌려줌: [dict(left, top, right, bottom)] (right·bottom 미포함)"""
    a = np.asarray(img.convert("RGB")).astype(int)
    H, W = a.shape[:2]
    gm = green_mask(a)
    white = (a[..., 0] > 235) & (a[..., 1] > 235) & (a[..., 2] > 235)
    # 1) 날짜 축: 초록이 (작은 틈을 빼면) 길게 이어지는 가로줄들의 묶음
    longest = np.zeros(H, int); span = [(0, 0)] * H
    for y in range(H):
        rs = _merge(_runs(gm[y]), max_gap)
        if rs:
            s, e = max(rs, key=lambda t: t[1] - t[0])
            longest[y] = e - s + 1; span[y] = (s, e)
    bands = _runs(longest >= min_width_frac * W)
    areas = []
    for y0, y1 in bands:
        x0 = min(span[y][0] for y in range(y0, y1 + 1)); x1 = max(span[y][1] for y in range(y0, y1 + 1))
        if y0 < 50: continue
        # 축 바로 위의 얇은 테두리(흰색이 아닌 줄, max_border줄 이하)는 건너뜀
        bottom = y0
        while bottom > y0 - max_border and white[bottom - 1, x0:x1 + 1].mean() < min_white:
            bottom -= 1
        if white[bottom - 1, x0:x1 + 1].mean() < min_white: continue
        # 2) 가격 축: 날짜 축 바로 위(최대 200줄)에서 거의 초록인 세로줄 → 가장 왼쪽 것이 그래프 오른쪽 끝
        look = gm[max(0, bottom - 200):bottom, x0:x1 + 1].mean(0)
        cols = np.where(look > 0.8)[0]
        cols = cols[cols > (x1 - x0) * 0.5]          # 오른쪽 절반에서만 찾음
        right = x0 + int(cols.min()) if len(cols) else x1 + 1
        # 3) 위쪽 끝: 날짜 축에서 위로 올라가며 흰 배경이 이어지는 동안
        wf = white[:bottom, x0:right].mean(1)
        top = bottom
        while top > 0 and wf[top - 1] >= min_white:
            top -= 1
        if bottom - top < 50 or right - x0 < 100: continue
        areas.append(dict(left=int(x0), top=int(top), right=int(right), bottom=int(bottom)))
    return areas

def main():
    ap = argparse.ArgumentParser(description="차트 그래프 영역 좌표 찾기")
    ap.add_argument("--image", type=Path, help="화면 대신 이 사진에서 찾기 (시험용)")
    ap.add_argument("--monitor", type=int, help="캡처할 모니터 번호 (기본: config의 monitor)")
    ap.add_argument("--delay", type=float, default=0, help="캡처 전 기다릴 초 (HTS 창을 앞으로 가져올 시간)")
    ap.add_argument("--top", type=int, default=0, help="'큰 봉'(화면 위) 차트로 쓸 후보 번호 (기본 0 = 가장 위)")
    ap.add_argument("--bottom", type=int, default=1, help="'작은 봉'(화면 아래) 차트로 쓸 후보 번호 (기본 1). -1 = 작은 봉 차트 안 씀")
    ap.add_argument("--set-bar-px", action="store_true", help="잰 봉 간격을 차트별 bar_px로 저장")
    ap.add_argument("--min-width", type=float, default=0.3, help="날짜 축이 화면 너비의 몇 배 이상이어야 하는지")
    ap.add_argument("--no-write", action="store_true", help="config.json에 저장하지 않음")
    ap.add_argument("--config", type=Path, default=C.CONFIG)
    args = ap.parse_args()

    cfg = C.load_config(args.config)
    if args.image:
        full, origin = Image.open(args.image).convert("RGB"), (0, 0)
        src = f"사진 {args.image}"
    else:
        if args.delay: print(f"{args.delay}초 뒤 캡처합니다. HTS 창을 앞으로 가져오세요."); time.sleep(args.delay)
        mon = args.monitor if args.monitor is not None else cfg["monitor"]
        full, origin = C.grab_full(mon)
        src = f"모니터 {mon} 화면 (메모리에만 있음)"
    print(f"캡처: {src}, 크기 {full.size}")

    areas = find_plot_areas(full, args.min_width)
    if not areas:
        print("초록 날짜 축을 찾지 못했습니다. 확인할 것:\n"
              "  1) HTS 차트가 화면에 보이는지 → --delay 5 로 다시 (5초 안에 HTS 창을 앞으로)\n"
              "  2) HTS가 다른 모니터에 있는지 → --monitor 2 (또는 3)\n"
              "     모니터 번호 확인: python -c \"import mss; print(mss.mss().monitors[1:])\"")
        sys.exit(1)
    import judge as J
    pick = {C.BIG: args.top, C.SMALL: args.bottom}
    for i, ar in enumerate(areas):
        use = [n for n, k in pick.items() if k == i]
        print(f"  후보 {i}: 왼쪽 {ar['left']}, 위 {ar['top']}, 너비 {ar['right'] - ar['left']}, 높이 {ar['bottom'] - ar['top']}"
              + (f"  ← {use[0]} 차트" if use else ""))
    if args.top >= len(areas):
        sys.exit(f"후보 {args.top}이(가) 없습니다.")

    ts = C.stamp(); out = C.ROOT / "logs" / "setup"
    found, marked = {}, (full.copy() if cfg.get("save_full_screenshot") else None)
    for name, k in pick.items():
        if k < 0:
            print(f"{name} 차트: 쓰지 않음 (--bottom -1)"); continue
        if k >= len(areas):
            print(f"{name} 차트: 후보 {k}이(가) 없어 찾지 못함. 화면에 위·아래 차트가 둘 다 보이는지 확인하세요. (이전 설정은 그대로 둠)")
            continue
        ar = areas[k]
        crop = full.crop((ar["left"], ar["top"], ar["right"], ar["bottom"]))
        region = dict(left=origin[0] + ar["left"], top=origin[1] + ar["top"],
                      width=ar["right"] - ar["left"], height=ar["bottom"] - ar["top"])
        lay = J.bar_layout(crop)
        measured = lay["봉간격_px"] if lay else None
        found[name] = (region, measured)
        p = C.save_keep(crop, out, f"{ts}_{C.CHART_FILE[name]}_영역")
        s = J.settings(cfg, name)
        zw = J.zoom_warning(lay, s) if lay else None
        meas = ("봉이 서로 붙어 있어 자동으로 잴 수 없음 (빽빽한 차트)" if lay and lay["봉이_붙음"] else f"{measured}px")
        note = f"\n   ⚠ {zw} → HTS 확대 비율을 원래대로 하거나, 봉 간격을 다시 정해야 함" if zw else ""
        print(f"{name} 차트(화면 {cfg['charts'][name]['위치']}): 확인용 사진 {p}\n"
              f"   봉 간격: 설정 {s['bar_px']}px, 측정 {meas}{note}")
        if marked is not None:
            ImageDraw.Draw(marked).rectangle((ar["left"], ar["top"], ar["right"] - 1, ar["bottom"] - 1),
                                             outline=(255, 0, 255), width=6)
    if marked is not None:
        print("화면 전체 사진(설정에서 켜져 있음):", C.save_keep(marked, out, f"{ts}_전체_표시"))
    else:
        print("화면 전체 사진은 저장하지 않음 (config의 save_full_screenshot = false)")

    if args.no_write:
        print("--no-write: config.json은 바꾸지 않음. 찾은 영역:", {n: r for n, (r, _) in found.items()})
        return
    for name, (region, measured) in found.items():
        cfg["charts"][name]["region"] = region
        if args.set_bar_px and measured: cfg["charts"][name]["bar_px"] = measured
    if not args.image: cfg["monitor"] = args.monitor if args.monitor is not None else cfg["monitor"]
    C.save_config(cfg, args.config)
    print("config.json에 저장:")
    for name in C.CHART_NAMES:
        c = cfg["charts"][name]
        print(f"  {name}(화면 {c['위치']}): 영역 {c['region']}, bar_px {c['bar_px'] or str(cfg.get('bar_px')) + ' (공통)'}")

if __name__ == "__main__":
    main()
