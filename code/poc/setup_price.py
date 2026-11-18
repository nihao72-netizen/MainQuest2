"""
실전 기록 1단계: HTS 현재가 칸 위치 지정 + OCR 시험

실행:  python code/poc/setup_price.py --delay 5       (5초 뒤 화면을 찍어 창을 띄움 — 그사이 HTS를 앞으로)
       python code/poc/setup_price.py --check 5        (저장된 현재가 칸을 2초 간격으로 5번 읽어 보기)

창에서 할 일 (마우스 드래그 두 번)
  1. 화면 전체(줄여서 보임)에서 현재가 숫자가 있는 곳을 넓게 드래그
  2. 크게 확대된 화면에서 현재가 숫자만 딱 맞게 드래그
  3. 아래에 OCR이 읽은 가격이 나옴 → HTS에 보이는 가격과 같으면 [저장], 다르면 [다시 고르기]
  Esc = 취소

- 화면 전체는 이 창에만 보여 주고 파일로 저장하지 않는다 (계좌·주문 정보 보호).
- 가격 축의 현재가 상자처럼 위아래로 움직이는 칸은 고르지 않는다. 위치가 고정된 현재가 숫자를 고른다.
- 저장: code/poc/config.json 의 "price_region" (화면 절대 좌표)
"""
import argparse, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture as C
import price_ocr as O

def pick_region(full):
    """tkinter 창에서 두 번 드래그 → 화면 사진 안의 (left, top, right, bottom). 취소하면 None"""
    import tkinter as tk
    from PIL import ImageTk
    result = {"box": None}
    root = tk.Tk(); root.title("현재가 칸 지정 (Esc = 취소)"); root.attributes("-topmost", True)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    maxw, maxh = int(sw * 0.85), int(sh * 0.75)
    info = tk.Label(root, font=("맑은 고딕", 14), anchor="w", justify="left"); info.pack(fill="x", padx=8, pady=4)
    canvas = tk.Canvas(root, cursor="cross", highlightthickness=0); canvas.pack()
    bottom = tk.Frame(root); bottom.pack(fill="x", padx=8, pady=6)
    msg = tk.Label(bottom, font=("맑은 고딕", 14), anchor="w"); msg.pack(side="left")
    state = {"stage": 1, "area": (0, 0, full.width, full.height), "scale": 1.0, "start": None, "rect": None, "tk": None}

    def show(area, text):
        l, t, r, b = area
        crop = full.crop(area)
        sc = min(maxw / crop.width, maxh / crop.height, 8.0)
        disp = crop.resize((max(1, int(crop.width * sc)), max(1, int(crop.height * sc))))
        state.update(area=area, scale=sc, tk=ImageTk.PhotoImage(disp))
        canvas.config(width=disp.width, height=disp.height); canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=state["tk"])
        info.config(text=text)

    def to_full(x, y):
        l, t, _, _ = state["area"]; sc = state["scale"]
        return int(l + x / sc), int(t + y / sc)

    def on_press(e):
        state["start"] = (e.x, e.y)
        state["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#ff00ff", width=2)

    def on_drag(e):
        if state["start"]: canvas.coords(state["rect"], *state["start"], e.x, e.y)

    def on_release(e):
        if not state["start"]: return
        (x0, y0), (x1, y1) = state["start"], (e.x, e.y); state["start"] = None
        (a, b), (c, d) = to_full(min(x0, x1), min(y0, y1)), to_full(max(x0, x1), max(y0, y1))
        if c - a < 4 or d - b < 4:
            msg.config(text="너무 작게 드래그했어요. 다시 드래그하세요."); return
        if state["stage"] == 1:
            state["stage"] = 2
            show((a, b, c, d), "2단계: 현재가 숫자만 딱 맞게 드래그하세요 (숫자 앞뒤로 아주 조금만 여유)")
            msg.config(text="")
        else:
            box = (a, b, c, d)
            p, txt, why = O.read_price(full.crop(box))
            result["box"] = box
            msg.config(text=f"OCR이 읽은 글자: {txt!r} → 가격: {p if p is not None else '읽기 실패 (' + why + ')'}"
                            "   HTS에 보이는 가격과 같으면 [저장]")

    def restart():
        state["stage"] = 1; result["box"] = None; msg.config(text="")
        show((0, 0, full.width, full.height), "1단계: 현재가 숫자가 있는 곳을 넓게 드래그하세요")

    def save():
        if result["box"] is None:
            msg.config(text="먼저 2단계에서 숫자를 드래그하세요."); return
        root.destroy()

    def cancel(_=None):
        result["box"] = None; root.destroy()

    tk.Button(bottom, text="저장", font=("맑은 고딕", 12), width=8, command=save).pack(side="right", padx=4)
    tk.Button(bottom, text="다시 고르기", font=("맑은 고딕", 12), width=10, command=restart).pack(side="right", padx=4)
    tk.Button(bottom, text="취소", font=("맑은 고딕", 12), width=8, command=cancel).pack(side="right", padx=4)
    canvas.bind("<ButtonPress-1>", on_press); canvas.bind("<B1-Motion>", on_drag); canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", cancel); root.protocol("WM_DELETE_WINDOW", cancel)
    restart(); root.mainloop()
    return result["box"]

def check(cfg, n, gap=2.0):
    """차트 위 현재가 칸 + 가격 축 현재가 상자를 함께 읽어 보기 (실전 기록과 같은 방법)"""
    import judge as J
    r = C.chart_region(cfg, C.BIG)
    if not r: sys.exit("큰 봉 차트 영역이 없습니다. 먼저 setup_region.py를 실행하세요.")
    s = J.settings(cfg, C.BIG); prev = None; got = {}
    out = C.ROOT / "logs" / "setup"
    for i in range(n):
        res = O.read_price_retry(r, cfg.get("price_field"), cfg.get("price_axis_width", 117), s["bar_px"], prev,
                                 save_path=out / f"{C.stamp()}_현재가_{i + 1}.png")
        if res["가격"] is not None: prev = res["가격"]
        key = res["출처"] or "실패"; got[key] = got.get(key, 0) + 1
        print(f"  {i + 1}: 가격 {res['가격']}  [{res['출처'] or res['실패이유']}]  (현재가 칸 {res['칸값']}, 가격 축 {res['축값']}, 시도 {res['시도']}번)")
        if i < n - 1: time.sleep(gap)
    print(f"결과: {got}. 검산용 사진(현재가 칸 | 가격 축 상자): {out}")
    print("HTS에 보이는 가격과 같은지 눈으로 확인하세요. 마우스를 차트 위에 두면 가격 축 상자가 십자선에 가려질 수 있습니다.")

def main():
    ap = argparse.ArgumentParser(description="HTS 현재가 칸 위치 지정 + OCR 시험")
    ap.add_argument("--delay", type=float, default=0, help="화면을 찍기 전 기다릴 초")
    ap.add_argument("--monitor", type=int, help="HTS가 있는 모니터 (기본: config의 monitor)")
    ap.add_argument("--check", type=int, metavar="N", help="현재가를 N번 읽어 보기 (기본 5번)")
    ap.add_argument("--drag", action="store_true", help="(예전 방식) 마우스로 고정 현재가 칸을 직접 지정")
    args = ap.parse_args()
    cfg = C.load_config()
    if args.check:
        check(cfg, args.check); return
    if not args.drag:
        check(cfg, 5); return
    if args.delay:
        print(f"{args.delay}초 뒤 화면을 찍습니다. HTS를 앞으로 가져오세요."); time.sleep(args.delay)
    mon = args.monitor if args.monitor is not None else cfg["monitor"]
    full, origin = C.grab_full(mon)          # 메모리에만. 파일로 저장하지 않음
    box = pick_region(full)
    if box is None:
        print("취소했습니다. config.json은 바꾸지 않았습니다."); return
    l, t, r, b = box
    big = C.chart_region(cfg, C.BIG)
    cfg["price_field"] = dict(dx=origin[0] + l - big["left"], dy=origin[1] + t - big["top"], w=r - l, h=b - t)
    C.save_config(cfg)
    print("저장: config.json price_field (큰 봉 그래프 영역 왼쪽 위 기준) =", cfg["price_field"])
    print("확인으로 3번 읽어 봅니다:"); check(cfg, 3)

if __name__ == "__main__":
    main()
