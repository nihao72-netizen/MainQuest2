"""
4) 분봉별 시험 사진 찍기 도우미 — 큰 봉 차트 영역만 찍어 data/시험용_분봉/<분봉>/ 에 저장

300분봉으로 학습한 AI가 다른 분봉에서도 같은 패턴을 알아보는지 시험하려고, HTS 큰 봉 차트를 시험할 분봉으로 바꾼 뒤
과거로 옮겨 가며 여러 장을 찍는다. 판정 결과는 보여 주지 않는다 (정답을 판정 없이 적기 위해).
분봉 이름은 이 시험 사진의 폴더 이름에만 쓴다 (실시간 기록에는 쓰지 않음).

실행:  python code/poc/capture_test.py 10분            (10분봉 사진 찍기, 목표 30장)
       python code/poc/capture_test.py 60분 --count 30

찍는 법 (자세히: code/poc/실행방법.md 6장)
  1. HTS 큰 봉 차트(화면 위)를 시험할 분봉으로 바꾼다. 확대 비율은 바꾸지 않는다.
  2. 차트를 과거로 옮긴다 (첫 장은 학습 사진과 겹치지 않는 시기부터).
  3. 터미널에서 Enter → 큰 봉 차트 영역만 저장.
  4. 차트를 "한 화면 폭 이상" 더 과거로 옮긴 뒤 다시 Enter. 목표 장수까지 반복. q + Enter = 끝.
  모양을 보고 고르지 말고, 한 화면씩 옮기며 차례로 찍는다 (좋아 보이는 모양만 고르면 시험이 쉬워짐).
"""
import argparse, re, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture as C
import judge as J

TEST_DIR = C.ROOT / "data" / "시험용_분봉"

def small_gray(img):
    return np.asarray(img.convert("L").resize((364, 84))).astype(float)

def main():
    ap = argparse.ArgumentParser(description="분봉별 시험 사진 찍기 (큰 봉 차트 영역만, 판정은 보여 주지 않음)")
    ap.add_argument("timeframe", help="폴더 이름으로 쓸 분봉. 예: 10분, 60분, 300분")
    ap.add_argument("--count", type=int, default=30, help="목표 장수 (기본 30)")
    ap.add_argument("--dir", type=Path, default=TEST_DIR, help="저장할 상위 폴더 (기본 data/시험용_분봉)")
    args = ap.parse_args()
    tf = args.timeframe.strip()
    if not re.fullmatch(r"[0-9A-Za-z가-힣]+", tf):
        sys.exit("분봉 이름은 글자·숫자만 (예: 10분, 60분, 300분)")
    cfg = C.load_config(); s = J.settings(cfg, C.BIG)
    region = C.chart_region(cfg, C.BIG)
    if not region:
        sys.exit("큰 봉 차트 영역이 없습니다. 먼저 setup_region.py를 실행하세요.")
    out = args.dir / tf; out.mkdir(parents=True, exist_ok=True)
    have = sorted(out.glob("*.png"))
    last = small_gray(C.Image.open(have[-1])) if have else None
    n = len(have)
    print(f"[{tf}] 큰 봉 차트 시험 사진 → {out}  (지금 {n}장, 목표 {args.count}장)")
    print("HTS 큰 봉 차트를 이 분봉으로 바꾸고 과거로 옮긴 뒤 Enter. 한 장 찍을 때마다 한 화면 폭 이상 더 과거로. q + Enter = 끝.")
    while n < args.count:
        try:
            cmd = input(f"  {n + 1}번째: Enter = 찍기, q = 끝 > ").strip().lower()
        except EOFError:
            break
        if cmd == "q":
            break
        img = C.grab_region(region)
        ok, chk = J.chart_check(img, s)
        if not ok:
            print("    저장 안 함: 큰 봉 차트가 다른 창에 가려진 것 같습니다. 창을 치우고 다시 Enter."); continue
        lay = J.bar_layout(img)
        zw = J.zoom_warning(lay, s) if lay else "봉을 찾지 못함"
        if zw:
            print(f"    저장 안 함: {zw}. HTS 큰 봉 차트의 확대 비율을 처음대로 맞추세요 (분봉만 바꾸고 확대는 그대로)."); continue
        g = small_gray(img)
        if last is not None and np.abs(g - last).mean() < 2.0:
            print("    저장 안 함: 바로 전 사진과 거의 같습니다. 차트를 한 화면 폭 이상 과거로 옮겼나요?"); continue
        n += 1
        p = C.save_keep(img, out, f"{tf}_{n:02d}", keep=0)
        last = g
        print(f"    저장 {p.name} ({n}/{args.count})")
    print(f"끝: [{tf}] {n}장. 정답 적기는 모든 분봉을 다 찍은 뒤: python code/poc/evaluate_timeframe.py --make-sheet")

if __name__ == "__main__":
    main()
