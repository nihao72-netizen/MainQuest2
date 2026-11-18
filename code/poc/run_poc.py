"""
PoC: 정기 실행 (캡처 → 판정 → 기록 → 알림) — 화면 위 "큰 봉" 차트와 아래 "작은 봉" 차트를 둘 다 판정

주문·매매와는 연결하지 않는다. 알림과 기록만 한다. 모든 처리는 내 PC 안에서만 한다.
분봉 이름(300분 등)은 쓰지 않는다 (사용자가 수시로 바꿈). 기록에는 "큰 봉 / 작은 봉"만 남긴다.

실행:
  python code/poc/run_poc.py                 # config의 간격(기본 5분)마다 반복, 멈추려면 Ctrl+C
  python code/poc/run_poc.py --once          # 한 번만
  python code/poc/run_poc.py --interval 3    # 3분 간격
  python code/poc/run_poc.py --charts 큰봉     # 큰 봉 차트만
  python code/poc/run_poc.py --once --image 큰봉.png --image-small 작은봉.png   # 화면 대신 사진으로 시험

남는 것 (logs/ 아래, 날짜·시각 이름, 덮어쓰지 않음, 보관 개수 = config keep_captures 또는 --keep):
  logs/판정기록*.csv                       차트 하나의 창 하나 = 한 줄. 차트(큰 봉/작은 봉), 모든 점수(반올림 없음), 모델 파일, 설정값
  logs/captures/<시각>_<큰봉|작은봉>.png     캡처한 차트 영역 (화면 전체는 저장하지 않음)
  logs/windows/<시각>_<차트>_창<N>.png       모델에 넣은 사진
  logs/images/<시각>_<차트>_확인.png         결과 글자를 얹은 확인용 이미지
  logs/실전시험/사진/<시각>_<차트>.png        정답 적기용 깨끗한 사진 (+ 정답표.csv 한 줄)
  logs/오류기록.txt                         실행 중 오류
"""
import argparse, sys, threading, time, traceback
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preprocess as P
import capture as C
import judge as J
import report as RP
import rules as R

RUN_DEFAULTS = {"interval_min": 5, "popup": True, "popup_only_on_change": True, "popup_big_alert": True}

TITLE_BIG = "큰 봉 방향 알림 (주문은 직접)"
TITLE_ENTRY = "진입 확인 (주문은 직접)"
ORDER_NOTE = "주문은 직접 하세요. 이 프로그램은 매매와 연결되어 있지 않습니다."
_popup_thread, _popup_title = None, None

def _msgbox(text, title):
    try:
        import ctypes
        # 정보 아이콘(0x40) + 맨 위(0x40000) + 앞으로 가져오기(0x10000)
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40 | 0x40000 | 0x10000)
    except Exception:
        pass   # 윈도우가 아니면 건너뜀

def _close_open_popup(title):
    """이미 떠 있는 알림 창을 닫는다 (창이 쌓이지 않게)"""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if hwnd: ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
    except Exception:
        pass

def popup(text, wait, title=TITLE_BIG):
    """wait=True(--once): 사용자가 닫을 때까지 기다림 → 프로그램이 끝나며 창이 같이 꺼지지 않음
    wait=False(반복 실행): 판정을 멈추지 않도록 따로 띄움. 이전 알림 창이 남아 있으면 닫고 새 창 하나만 띄움"""
    global _popup_thread, _popup_title
    text = f"{text}\n\n{ORDER_NOTE}"
    if wait:
        _msgbox(text, title); return
    if _popup_thread is not None and _popup_thread.is_alive():
        _close_open_popup(_popup_title); _popup_thread.join(timeout=2)
    _popup_thread = threading.Thread(target=_msgbox, args=(text, title), daemon=True)
    _popup_title = title
    _popup_thread.start()

ENTRY_COLUMNS = ["시각", "실행ID", "진입확인", "방향", "설명", "큰봉_판정", "큰봉_방향", "작은봉_판정", "작은봉_방향",
                 "모델_dir3", "모델_cls11", "설정_rule", "설정_min_dir3_score", "설정_window_combine", "설정_main_bars",
                 "큰봉_bar_px", "작은봉_bar_px"]

LABEL_COLUMNS = ["실행ID", "차트", "시각", "사진", "정답", "라벨의심", "메모"]

def labeling_image(img, res, s):
    """정답 적기용 사진: 결과 글자·색이 없는 깨끗한 차트 + 기준 창 시작 위치(회색 점선, 판정과 무관하게 항상 같은 모양)"""
    from PIL import ImageDraw
    out = img.copy(); d = ImageDraw.Draw(out)
    main = min(res["windows"], key=lambda w: abs(w["bars"] - s["main_bars"])) if res["windows"] else None
    if main:
        x = main["x0"]
        for y in range(0, out.height, 16):
            d.line((x, y, x, min(out.height, y + 8)), fill=(150, 150, 150), width=2)
        d.text((x + 6, out.height - 22), f"{main['bars']}봉 시작 — 이 선부터 오른쪽 끝까지의 방향을 적기",
               fill=(120, 120, 120), font=RP._font(18))
    return out

def migrate_label_sheet(sheet):
    """예전 정답표(차트 열 없음)는 모두 큰 봉 차트였으므로 '차트=큰 봉'을 채워 새 열 구성으로 바꿈"""
    import csv
    if not sheet.exists():
        return
    with open(sheet, encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f), None)
    if header == LABEL_COLUMNS:
        return
    with open(sheet, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    with open(sheet, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=LABEL_COLUMNS); wr.writeheader()
        for r in rows:
            wr.writerow({**{k: r.get(k, "") or "" for k in LABEL_COLUMNS}, "차트": r.get("차트") or C.BIG})

def save_for_labeling(img, res, s, when, run_id, chart, log_dir):
    """실전 시험용: 깨끗한 차트 사진 + 정답표 한 줄 (판정 결과는 정답표에 넣지 않음). 사진은 자동으로 지우지 않음"""
    import csv
    base = log_dir / "실전시험"
    pic = C.save_keep(labeling_image(img, res, s), base / "사진", f"{run_id}_{C.CHART_FILE[chart]}", keep=0)
    sheet = base / "정답표.csv"
    try:
        migrate_label_sheet(sheet)
        new = not sheet.exists()
        with open(sheet, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=LABEL_COLUMNS)
            if new: wr.writeheader()
            wr.writerow({"실행ID": run_id, "차트": chart, "시각": when.isoformat(timespec="seconds"),
                         "사진": f"사진/{pic.name}", "정답": "", "라벨의심": "", "메모": ""})
    except PermissionError:
        print("  (정답표.csv가 엑셀에 열려 있어 줄을 추가하지 못함. 사진은 저장됨 → "
              "나중에 python code/poc/evaluate_practice.py --sync 로 채움)", flush=True)

def judge_chart(chart, img, src, judge, cfg, when, run_id, log_dir, keep, tags):
    """차트 하나 판정 → 저장 → 기록. 돌려주는 값: 판정 결과"""
    s = J.settings(cfg, chart)
    res = J.judge_region(img, judge, s)
    res["기준창"] = s["main_bars"]
    tag = C.CHART_FILE[chart]
    files = {"입력": src}
    if res.get("차트아님"):
        # 다른 창에 가려진 화면 → 차트가 아닌 내용이 기록에 남지 않도록 사진은 저장하지 않는다
        files["캡처파일"] = files["확인이미지"] = "저장 안 함 (차트 아님)"
    else:
        files["캡처파일"] = str(C.save_keep(img, log_dir / "captures", f"{run_id}_{tag}", keep))
        for w in res["windows"]:
            C.save_keep(w["img"], log_dir / "windows", f"{run_id}_{tag}_창{w['bars']}", keep * max(1, len(res["windows"])))
        files["확인이미지"] = str(C.save_keep(RP.annotate(img, res, when, chart=chart), log_dir / "images",
                                         f"{run_id}_{tag}_확인", keep))
    res["csv"] = RP.append_csv(log_dir / "판정기록.csv",
                               RP.csv_rows(when, run_id, res, s, C.chart_region(cfg, chart), tags, files, chart))
    if not res.get("차트아님") and cfg.get("practice_test", True):
        save_for_labeling(img, res, s, when, run_id, chart, log_dir)
    print(RP.console_line(when, res, chart), flush=True)
    return res

def run_once(judge, cfg, args, charts, log_dir, keep, tags, last_alert):
    when = datetime.now(); run_id = C.stamp(when)
    results = {}
    for chart in charts:
        if args.image or args.image_small:
            img_path = args.image if chart == C.BIG else args.image_small
            if not img_path: continue
            img = P.Image.open(img_path).convert("RGB"); src = str(img_path)
        else:
            img = C.grab_region(C.chart_region(cfg, chart)); src = f"화면 {chart} 차트"
        results[chart] = judge_chart(chart, img, src, judge, cfg, when, run_id, log_dir, keep, tags)
    # ---- 진입 확인: 큰 봉 알림 방향 = 작은 봉 알림 방향 ----
    big, small = results.get(C.BIG), results.get(C.SMALL)
    pair = lambda r: None if (r is None or r.get("차트아님")) else (r["판정"], r["방향"])
    ok, d, why = R.entry_check(pair(big), pair(small))
    if small is not None or big is None:     # 작은 봉을 판정한 경우에만 진입 확인을 따지고 기록
        print(f"{when:%Y-%m-%d %H:%M:%S} | [{R.ENTRY}] " + (f"{why} → 진입 확인({d}) — 주문은 직접" if ok else f"아님 — {why}"),
              flush=True)
        sb, ss = J.settings(cfg, C.BIG), J.settings(cfg, C.SMALL)
        RP.append_rows(log_dir / "진입확인기록.csv", ENTRY_COLUMNS, [{
            "시각": when.isoformat(timespec="seconds"), "실행ID": run_id, "진입확인": "예" if ok else "아니오",
            "방향": d or "", "설명": why,
            "큰봉_판정": big["판정"] if big else "", "큰봉_방향": (big or {}).get("방향") or "",
            "작은봉_판정": small["판정"] if small else "", "작은봉_방향": (small or {}).get("방향") or "",
            "모델_dir3": tags["dir3"], "모델_cls11": tags["cls11"], "설정_rule": sb["rule"],
            "설정_min_dir3_score": sb["min_dir3_score"], "설정_window_combine": sb["window_combine"],
            "설정_main_bars": sb["main_bars"], "큰봉_bar_px": sb["bar_px"], "작은봉_bar_px": ss["bar_px"]}])
    # ---- 알림 창: 진입 확인 > 큰 봉 알림. 창은 하나만 ----
    if ok:
        key, title = ("진입 확인", d), TITLE_ENTRY
        text = (f"{when:%H:%M}  진입 확인: {d}\n큰 봉 알림({d}) = 작은 봉 알림({d})\n\n"
                + RP.console_line(when, big, C.BIG).split(" | ", 1)[1] + "\n" + RP.console_line(when, small, C.SMALL).split(" | ", 1)[1])
    elif big and big["판정"] == R.ALERT and cfg["popup_big_alert"]:
        key, title = ("큰 봉 알림", big["방향"]), TITLE_BIG
        text = RP.console_line(when, big, C.BIG).replace(" | ", "\n")
    else:
        key = None
    if key and cfg["popup"] and not args.no_popup:
        if not cfg["popup_only_on_change"] or key != last_alert:
            if args.once: print("알림 창을 닫으면 프로그램이 끝납니다.", flush=True)
            popup(text, wait=args.once, title=title)
    csv_path = next((r["csv"] for r in results.values()), None)
    return key, csv_path

def main():
    ap = argparse.ArgumentParser(description="큰 봉·작은 봉 차트 방향 판정 PoC (알림·기록만)")
    ap.add_argument("--once", action="store_true", help="한 번만 실행")
    ap.add_argument("--interval", type=float, help="반복 간격(분). 기본: config interval_min")
    ap.add_argument("--keep", type=int, help="사진 보관 개수 (폴더마다). 기본: config keep_captures, 0 = 지우지 않음")
    ap.add_argument("--image", type=Path, help="화면 대신 이 큰 봉 차트 영역 사진으로 판정 (시험용)")
    ap.add_argument("--image-small", type=Path, help="화면 대신 이 작은 봉 차트 영역 사진으로 판정 (시험용)")
    ap.add_argument("--charts", default="큰봉,작은봉", help="판정할 차트 (쉼표로): 큰봉,작은봉 (기본 둘 다)")
    ap.add_argument("--log-dir", type=Path, default=C.ROOT / "logs")
    ap.add_argument("--no-popup", action="store_true", help="알림 창 띄우지 않음")
    args = ap.parse_args()

    cfg = C.load_config()
    for k, v in RUN_DEFAULTS.items(): cfg.setdefault(k, v)
    keep = args.keep if args.keep is not None else cfg["keep_captures"]
    interval = args.interval if args.interval is not None else cfg["interval_min"]
    charts = [C.chart_name(x) for x in args.charts.split(",") if x.strip()]
    if not (args.image or args.image_small):
        missing = [c for c in charts if not C.chart_region(cfg, c)]
        for c in missing: print(f"{c} 차트의 영역이 config.json에 없어 건너뜁니다 (setup_region.py로 정할 수 있음).")
        charts = [c for c in charts if c not in missing]
        if not charts:
            sys.exit("판정할 차트가 없습니다. 먼저 code/poc/setup_region.py를 실행하세요.")
    s = J.settings(cfg)
    md = Path(s["models_dir"]); md = md if md.is_absolute() else C.ROOT / md
    judge = J.Judge(md)
    tags = {"dir3": RP.model_tag(md, "dir3"), "cls11": RP.model_tag(md, "cls11")}
    print(f"시작: 모델 {tags['dir3']} / {tags['cls11']}")
    chart_desc = ", ".join(f"{c}(봉 간격 {J.settings(cfg, c)['bar_px']}px)" for c in charts)
    print(f"설정: 차트 {chart_desc}, 창 {s['window_bars']}봉, 규칙 {s['rule']}(3분류 점수 최소값 {s['min_dir3_score']}), "
          f"창 묶기 {s['window_combine']}(기준 {s['main_bars']}봉), 간격 {interval}분, 보관 {keep}장"
          + (" (한 번만)" if args.once else " — 멈추려면 Ctrl+C"))

    last_alert, nxt = None, datetime.now()
    try:
        while True:
            try:
                last_alert, csv_path = run_once(judge, cfg, args, charts, args.log_dir, keep, tags, last_alert)
            except Exception as e:
                msg = f"{datetime.now():%Y-%m-%d %H:%M:%S} 오류: {e}"
                print(msg, flush=True)
                args.log_dir.mkdir(parents=True, exist_ok=True)
                with open(args.log_dir / "오류기록.txt", "a", encoding="utf-8") as f:
                    f.write(msg + "\n" + traceback.format_exc() + "\n")
                if args.once: sys.exit(1)
            if args.once:
                print("기록:", csv_path); break
            nxt += timedelta(minutes=interval)
            while nxt <= datetime.now(): nxt += timedelta(minutes=interval)   # 밀렸으면 다음 칸으로
            time.sleep(max(0.0, (nxt - datetime.now()).total_seconds()))
    except KeyboardInterrupt:
        print("\n멈춤 (Ctrl+C)")

if __name__ == "__main__":
    main()
