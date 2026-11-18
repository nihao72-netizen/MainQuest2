"""
실전 기록 2단계: 단축키(Ctrl+Alt+J) → 차트 캡처 + 현재가 + AI 판정(보여 주지 않음) → 내 판단 선택 창

실행:  python code/poc/record_live.py            (켜 두면 아무 때나 Ctrl+Alt+J. 끝내려면 이 터미널에서 Ctrl+C)

순서 (단축키를 누를 때마다)
  ① 큰 봉·작은 봉 차트 영역 캡처  ② 현재가 읽기(p0, 차트 위 현재가 칸 + 가격 축 상자)
  ③ AI 판정 계산(큰 봉·작은 봉·진입 확인) → 파일에만 저장, 화면에는 보여 주지 않음
  ④ 선택 창: [오른다] [내린다] [모르겠다] + 메모 — 차트가 없는 모니터에 띄움 (캡처를 먼저 하고 창을 띄움)
  ⑤ 내 판단 저장

남는 것 (logs/실전기록/, GitHub에 올리지 않음)
  내판단.csv         기록ID, 시각, 내 판단, 메모, 현재가 p0와 출처, 사진 경로
  AI판정.csv         같은 기록ID의 AI 요약 (큰 봉·작은 봉 최종 판정, 진입 확인, 큰 봉 150봉 창 점수) — 결과 표를 보기 전에는 열지 않기
  AI판정_창별.csv     창별 모든 점수 (판정기록.csv와 같은 열)
  사진/<기록ID>_<큰봉|작은봉>.png, 가격/<기록ID>_0.png

주문·매매와는 연결하지 않는다. 투자 조언이 아니다.
"""
import argparse, ctypes, queue, sys, threading, time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture as C
import judge as J
import report as RP
import rules as R
import price_ocr as O

LIVE_DEFAULTS = {"hotkey": "Ctrl+Alt+J"}
MY_COLUMNS = ["기록ID", "시각", "차트시점", "내판단", "실제결과", "큰봉분봉", "메모", "현재가", "현재가_출처", "현재가_현재가칸", "현재가_가격축", "현재가_실패이유",
              "가격사진", "큰봉사진", "작은봉사진", "선택까지_초"]
AI_COLUMNS = ["기록ID", "시각", "큰봉_판정", "큰봉_방향", "큰봉_근거", "작은봉_판정", "작은봉_방향", "작은봉_근거",
              "진입확인", "진입방향", "큰봉_150봉_dir3", "큰봉_150봉_dir3점수", "큰봉_150봉_cls11", "큰봉_150봉_cls11방향",
              "큰봉_150봉_cls11점수", "작은봉_150봉_dir3", "작은봉_150봉_dir3점수", "작은봉_150봉_cls11방향",
              "경고", "모델_dir3", "모델_cls11", "설정_rule", "설정_min_dir3_score", "설정_window_combine", "설정_main_bars"]
CHOICES = ["오른다", "내린다", "모르겠다"]

# ---------------- 전역 단축키 (윈도우 RegisterHotKey: 어느 창이 앞에 있어도 동작) ----------------
MOD = {"ctrl": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT, WM_HOTKEY = 0x4000, 0x0312

def parse_hotkey(s):
    parts = [p.strip().lower() for p in s.split("+")]
    mods = sum(MOD[p] for p in parts[:-1]) | MOD_NOREPEAT
    key = parts[-1].upper()
    vk = ord(key) if len(key) == 1 else {"F%d" % i: 0x6F + i for i in range(1, 13)}[key]
    return mods, vk

def hotkey_thread(hotkey, q, ready):
    u = ctypes.windll.user32
    mods, vk = parse_hotkey(hotkey)
    ok = u.RegisterHotKey(None, 1, mods, vk)
    ready.put(bool(ok))
    if not ok: return
    msg = wintypes.MSG()
    while u.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == WM_HOTKEY:
            q.put(time.time())
    u.UnregisterHotKey(None, 1)

# ---------------- 선택 창 위치: 차트가 없는 모니터 ----------------
def choice_position(cfg, w, h):
    """차트 영역이 없는 모니터의, 차트 모니터 쪽 가장자리 세로 가운데. 그런 모니터가 없으면 큰 봉·작은 봉 차트 사이"""
    import mss
    with (mss.MSS() if hasattr(mss, "MSS") else mss.mss()) as s:
        mons = s.monitors[1:]
    rects = [C.chart_region(cfg, n) for n in C.CHART_NAMES if C.chart_region(cfg, n)]
    def has_chart(m):
        return any(not (r["left"] >= m["left"] + m["width"] or r["left"] + r["width"] <= m["left"] or
                        r["top"] >= m["top"] + m["height"] or r["top"] + r["height"] <= m["top"]) for r in rects)
    free = [m for m in mons if not has_chart(m)]
    if free and rects:
        cx = sum(r["left"] for r in rects) / len(rects)
        m = min(free, key=lambda m: abs(m["left"] + m["width"] / 2 - cx))
        x = m["left"] + m["width"] - w - 40 if cx > m["left"] + m["width"] / 2 else m["left"] + 40
        return int(x), int(m["top"] + (m["height"] - h) / 2)
    big, small = C.chart_region(cfg, C.BIG), C.chart_region(cfg, C.SMALL)
    if big and small:
        return int(big["left"] + big["width"] - w - 200), int(big["top"] + big["height"] + 30)
    return 100, 100

# ---------------- 단축키 한 번 처리 ----------------
def capture_all(cfg, judge, tags, log_dir, rid, when, ref_price=None):
    """① 캡처 ② 현재가(기준값 ref_price와 비교) ③ AI 판정(저장만). 선택 창을 띄우기 전에 끝낸다. 돌려주는 값: 내판단.csv에 넣을 앞부분"""
    base = log_dir / "실전기록"
    imgs = {}
    for chart in C.CHART_NAMES:
        reg = C.chart_region(cfg, chart)
        if reg: imgs[chart] = C.grab_region(reg)
    big_reg = C.chart_region(cfg, C.BIG)
    sb = J.settings(cfg, C.BIG)
    pr = O.read_price_retry(big_reg, cfg.get("price_field"), cfg.get("price_axis_width", 117), sb["bar_px"], ref_price,
                            save_path=base / "가격" / f"{rid}_0.png")
    paths, results = {}, {}
    for chart, img in imgs.items():
        s = J.settings(cfg, chart)
        res = J.judge_region(img, judge, s)
        results[chart] = res
        if res.get("차트아님"):
            paths[chart] = "저장 안 함 (차트 아님)"
        else:
            paths[chart] = str(C.save_keep(img, base / "사진", f"{rid}_{C.CHART_FILE[chart]}", keep=0))
        RP.append_csv(base / "AI판정_창별.csv", RP.csv_rows(when, rid, res, s, C.chart_region(cfg, chart), tags,
                                                            {"캡처파일": paths[chart]}, chart))
    big, small = results.get(C.BIG), results.get(C.SMALL)
    pair = lambda r: None if (r is None or r.get("차트아님")) else (r["판정"], r["방향"])
    ok, d, _ = R.entry_check(pair(big), pair(small))
    def w150(res, key):
        if not res or not res["windows"]: return ""
        w = min(res["windows"], key=lambda w: abs(w["bars"] - sb["main_bars"]))
        return {"dir3": w["dir3"], "dir3점수": repr(w["dir3_점수"][w["dir3"]]), "cls11": w["cls11"],
                "cls11방향": w["cls11_방향"], "cls11점수": repr(w["cls11_점수"][w["cls11"]])}[key]
    RP.append_rows(base / "AI판정.csv", AI_COLUMNS, [{
        "기록ID": rid, "시각": when.isoformat(timespec="seconds"),
        "큰봉_판정": big["판정"] if big else "", "큰봉_방향": (big or {}).get("방향") or "", "큰봉_근거": (big or {}).get("근거", ""),
        "작은봉_판정": small["판정"] if small else "", "작은봉_방향": (small or {}).get("방향") or "", "작은봉_근거": (small or {}).get("근거", ""),
        "진입확인": "예" if ok else "아니오", "진입방향": d or "",
        "큰봉_150봉_dir3": w150(big, "dir3"), "큰봉_150봉_dir3점수": w150(big, "dir3점수"), "큰봉_150봉_cls11": w150(big, "cls11"),
        "큰봉_150봉_cls11방향": w150(big, "cls11방향"), "큰봉_150봉_cls11점수": w150(big, "cls11점수"),
        "작은봉_150봉_dir3": w150(small, "dir3"), "작은봉_150봉_dir3점수": w150(small, "dir3점수"),
        "작은봉_150봉_cls11방향": w150(small, "cls11방향"),
        "경고": " / ".join(sum([(r or {}).get("경고", []) for r in (big, small)], [])),
        "모델_dir3": tags["dir3"], "모델_cls11": tags["cls11"], "설정_rule": sb["rule"],
        "설정_min_dir3_score": sb["min_dir3_score"], "설정_window_combine": sb["window_combine"], "설정_main_bars": sb["main_bars"]}])
    warn = [f"{c}: 차트가 가려진 것 같음" for c, r in results.items() if r.get("차트아님")]
    return dict(기록ID=rid, 시각=when.isoformat(timespec="seconds"), 현재가=pr["가격"] if pr["가격"] is not None else "",
                현재가_출처=pr["출처"], 현재가_현재가칸=pr["칸값"] if pr["칸값"] is not None else "",
                현재가_가격축=pr["축값"] if pr["축값"] is not None else "", 현재가_실패이유=pr["실패이유"],
                가격사진=pr.get("사진") or "", 큰봉사진=paths.get(C.BIG, ""), 작은봉사진=paths.get(C.SMALL, "")), warn

TF_CHOICES = ["1분", "3분", "10분", "60분", "300분", "기타"]

def last_timeframe(base, default="300분"):
    """내판단.csv 마지막 기록의 큰 봉 분봉 (없으면 default) — 분봉을 바꿨을 때만 고치면 되게"""
    p = base / "내판단.csv"
    if p.exists():
        import csv
        with open(p, encoding="utf-8-sig", newline="") as f:
            vals = [r.get("큰봉분봉", "") for r in csv.DictReader(f) if r.get("큰봉분봉")]
        if vals: return vals[-1]
    return default

def ensure_columns(path, columns):
    """예전 열 구성의 CSV에 새 열(예: 큰봉분봉)을 빈칸으로 더해 같은 파일을 계속 쓰게 함 (파일이 _v2로 쪼개지지 않게)"""
    import csv
    if not path.exists(): return
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f); header = rd.fieldnames or []; rows = list(rd)
    if header == columns or not set(header) <= set(columns): return
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns); w.writeheader()
        for r in rows: w.writerow({k: r.get(k, "") for k in columns})

NOW, PAST = "지금 차트", "과거 차트"
PAST_CHOICES = ["올랐음", "내렸음", "횡보"]
PAST_RULE = "찍은 지점에서 다음 20봉 안에 확실히 오르면 올랐음, 확실히 내리면 내렸음, 아니면 횡보"

def ask_choice(root, pos, rid, price_text, auto=None, tf_default="300분", auto_mode=NOW):
    """선택 창. 돌려주는 값: (차트시점 '지금 차트'/'과거 차트', 선택 또는 '취소', 메모, 큰 봉 분봉)
    - 지금 차트: 오른다 / 내린다 / 모르겠다 (내 판단) → 정해 둔 시간 뒤 가격을 자동으로 확인
    - 과거 차트: 올랐음 / 내렸음 / 횡보 (앞으로 넘겨서 본 실제 결과, 기준 PAST_RULE) → 가격 확인 안 함
    차트시점은 매번 '지금 차트'로 시작한다 (과거 차트로 둔 채 잊고 실전 기록을 하지 않게)"""
    import tkinter as tk
    from tkinter import ttk
    out = {"mode": NOW, "choice": "취소", "memo": "", "tf": tf_default}
    win = tk.Toplevel(root); win.title(f"내 판단 기록 #{rid}"); win.attributes("-topmost", True)
    win.geometry(f"+{pos[0]}+{pos[1]}"); win.resizable(False, False)
    f = ("맑은 고딕", 16)
    mode = tk.StringVar(value=NOW)
    mrow = tk.Frame(win); mrow.pack(pady=(14, 2))
    for m in (NOW, PAST):
        tk.Radiobutton(mrow, text=m, value=m, variable=mode, font=("맑은 고딕", 13), indicatoron=False, width=10,
                       selectcolor="#ffd966", command=lambda: refresh()).pack(side="left", padx=4)
    title = tk.Label(win, font=f); title.pack(padx=20, pady=(8, 2))
    sub = tk.Label(win, font=("맑은 고딕", 11), fg="#555"); sub.pack(pady=(0, 6))
    tfrow = tk.Frame(win); tfrow.pack(pady=(0, 8))
    tk.Label(tfrow, text="큰 봉 분봉", font=("맑은 고딕", 12)).pack(side="left", padx=(0, 8))
    tfbox = ttk.Combobox(tfrow, values=TF_CHOICES, font=("맑은 고딕", 12), width=8)
    tfbox.set(tf_default); tfbox.pack(side="left")
    tk.Label(tfrow, text="(지난번 값. 분봉을 바꿨을 때만 고치세요. 목록에 없으면 직접 입력, 예: 16분)",
             font=("맑은 고딕", 9), fg="#777").pack(side="left", padx=8)
    row = tk.Frame(win); row.pack(padx=16, pady=4)
    def labels():
        return CHOICES if mode.get() == NOW else PAST_CHOICES
    def pick(i):
        out.update(mode=mode.get(), choice=labels()[i], memo=memo.get().strip(), tf=tfbox.get().strip() or tf_default)
        win.destroy()
    colors = ["#d33", "#26c", "#666"]
    btns = [tk.Button(row, font=f, width=8, fg="white", bg=c, activebackground=c, command=lambda i=i: pick(i))
            for i, c in enumerate(colors)]
    for b in btns: b.pack(side="left", padx=8)
    tk.Label(win, text="메모 (선택)", font=("맑은 고딕", 11)).pack(anchor="w", padx=20, pady=(12, 0))
    memo = tk.Entry(win, font=("맑은 고딕", 12), width=40); memo.pack(padx=20, pady=(0, 6))
    hint = tk.Label(win, font=("맑은 고딕", 9), fg="#777"); hint.pack(padx=12, pady=(0, 12))
    def refresh():
        names = labels()
        for i, b in enumerate(btns): b.config(text=f"{names[i]}\n({i + 1})")
        if mode.get() == NOW:
            title.config(text="지금 큰 봉 차트, 앞으로 어떻게 될까요?")
            sub.config(text=f"현재가 {price_text}   (AI 판정은 보여 주지 않습니다)")
            win.configure(bg=win.cget("bg"))
        else:
            title.config(text="과거 차트: 실제로 어떻게 됐나요?")
            sub.config(text=f"기준: {PAST_RULE}.  가격 확인 예약은 하지 않습니다.")
        hint.config(text=f"키보드: 1 {names[0]} · 2 {names[1]} · 3 {names[2]} · Esc 취소   (메모 칸에 입력 중에는 버튼을 누르세요)")
    def key(e):
        if win.focus_get() in (memo, tfbox): return       # 메모·분봉 칸에 입력 중에는 숫자 키를 선택으로 쓰지 않음
        if e.char in "123" and e.char: pick(int(e.char) - 1)
    win.bind("<Key>", key); win.bind("<Escape>", lambda e: win.destroy())
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    refresh(); win.lift(); win.focus_force()
    if auto:                                               # 시험용 자동 선택
        def do_auto():
            mode.set(auto_mode); refresh(); pick(labels().index(auto))
        win.after(800, do_auto)
    root.wait_window(win)
    return out["mode"], out["choice"], out["memo"], out["tf"]

def read_mine(base):
    """내판단.csv (+ 열 구성이 바뀌어 생긴 내판단_v2.csv 등)를 기록ID 기준으로 합쳐 읽기"""
    import csv
    rows = {}
    for p in sorted(base.glob("내판단*.csv")):
        if "백업" in p.name: continue
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f): rows[r["기록ID"]] = r
    return list(rows.values())

def latest_good_price(base, max_age_h=12):
    """최근 max_age_h시간 안에 믿을 수 있게 읽은 현재가 (현재가 OCR의 기준값). 과거 차트 기록은 뺀다"""
    import csv
    best = None
    now = time.time()
    def consider(ts, p):
        nonlocal best
        try: t = datetime.fromisoformat(ts).timestamp(); p = float(p)
        except (ValueError, TypeError): return
        if now - t <= max_age_h * 3600 and (best is None or t > best[0]): best = (t, p)
    for r in read_mine(base):
        if r.get("차트시점") != PAST and r.get("현재가") and r.get("현재가_출처") == "두 곳 일치":
            consider(r["시각"], r["현재가"])
    res = base / "가격결과.csv"
    if res.exists():
        with open(res, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("상태") == "읽음" and r.get("출처") == "두 곳 일치": consider(r["읽은시각"], r["p1"])
    return best[1] if best else None

# ---------------- 3단계: 정해 둔 시간 뒤 현재가 자동 기록 ----------------
DEFAULT_HORIZONS = [{"이름": "30분", "분": 30, "기준폭": 20},
                    {"이름": "2시간", "분": 120, "기준폭": 40},
                    {"이름": "1일", "분": 1440, "기준폭": 100}]
RESULT_COLUMNS = ["기록ID", "시간", "예정시각", "읽은시각", "늦음_초", "상태", "p0", "p1", "변화", "기준폭", "결과_기록당시",
                  "출처", "실패이유", "가격사진"]

def tolerance_sec(h_sec):
    """조금 늦게 읽어도 인정하는 범위: 시간의 10%, 최소 3분, 최대 30분 (30분→3분, 2시간→12분, 1일→30분)"""
    return min(max(0.1 * h_sec, 180), 1800)

def direction_of(change, thr):
    """변화량 → 실제 방향. 기준 폭 이상 오르면 올랐음, 기준 폭 이상 내리면 내렸음, 그 사이는 변동 작음"""
    if change >= thr: return "올랐음"
    if change <= -thr: return "내렸음"
    return "변동 작음"

class PriceScheduler:
    """기록마다 시간(30분·2시간·1일) 뒤 현재가를 읽어 가격결과.csv에 남긴다. 껐다 켜도 파일에서 다시 잡는다."""
    def __init__(self, cfg, base, horizons, retry_sec=30):
        self.cfg, self.base, self.horizons, self.retry_sec = cfg, base, horizons, retry_sec
        self.pending = {}            # (기록ID, 시간이름) → dict(t0, p0, due, h, next_try, 실패이유)
        self.prev_price = latest_good_price(base)     # 최근 12시간 안에 믿을 수 있게 읽은 값 (없으면 None)

    def add(self, rid, t0, p0):
        for h in self.horizons:
            due = t0 + h["초"]
            self.pending[(rid, h["이름"])] = dict(rid=rid, t0=t0, p0=p0, due=due, h=h, next_try=due, 실패이유="")

    def rebuild(self):
        """켤 때: 내판단.csv의 기록 중 가격결과.csv에 아직 없는 (기록, 시간)을 다시 잡는다"""
        done = set()
        res = self.base / "가격결과.csv"
        if res.exists():
            import csv
            with open(res, encoding="utf-8-sig", newline="") as f:
                done = {(r["기록ID"], r["시간"]) for r in csv.DictReader(f)}
        rows = [r for r in read_mine(self.base) if r.get("내판단") in CHOICES and r.get("차트시점") != PAST]
        n = 0
        for r in rows:
            t0 = datetime.fromisoformat(r["시각"]).timestamp()
            p0 = float(r["현재가"]) if r["현재가"] else None
            for h in self.horizons:
                if (r["기록ID"], h["이름"]) not in done:
                    self.pending[(r["기록ID"], h["이름"])] = dict(rid=r["기록ID"], t0=t0, p0=p0, due=t0 + h["초"], h=h,
                                                                next_try=t0 + h["초"], 실패이유=""); n += 1
        return n

    def _write(self, item, now, 상태, p1=None, 출처="", why="", pic=""):
        h, p0 = item["h"], item["p0"]
        chg = (p1 - p0) if (p1 is not None and p0 is not None) else None
        RP.append_rows(self.base / "가격결과.csv", RESULT_COLUMNS, [{
            "기록ID": item["rid"], "시간": h["이름"], "예정시각": datetime.fromtimestamp(item["due"]).isoformat(timespec="seconds"),
            "읽은시각": datetime.fromtimestamp(now).isoformat(timespec="seconds") if 상태 == "읽음" else "",
            "늦음_초": round(now - item["due"]) if 상태 == "읽음" else "", "상태": 상태,
            "p0": "" if p0 is None else p0, "p1": "" if p1 is None else p1, "변화": "" if chg is None else round(chg, 2),
            "기준폭": h["기준폭"], "결과_기록당시": direction_of(chg, h["기준폭"]) if chg is not None else "",
            "출처": 출처, "실패이유": why, "가격사진": pic}])
        return chg

    def tick(self, now=None):
        """예정 시각이 된 것을 읽는다. 허용 범위를 넘긴 것은 놓침/읽기실패로 남긴다"""
        now = now or time.time()
        for key in sorted(self.pending, key=lambda k: self.pending[k]["due"]):
            it = self.pending[key]
            if now < it["next_try"]: continue
            late = now - it["due"]; tol = tolerance_sec(it["h"]["초"])
            if late > tol:
                state = "읽기실패" if it["실패이유"] else "놓침"
                self._write(it, now, state, why=it["실패이유"] or "그 시각에 프로그램이 꺼져 있었음")
                print(f"  [{it['h']['이름']} 뒤] 기록 #{it['rid']}: {state}" + (f" ({it['실패이유']})" if it["실패이유"] else ""))
                del self.pending[key]; continue
            big = C.chart_region(self.cfg, C.BIG); s = J.settings(self.cfg, C.BIG)
            pic = self.base / "가격" / f"{it['rid']}_{it['h']['이름']}.png"
            pr = O.read_price_retry(big, self.cfg.get("price_field"), self.cfg.get("price_axis_width", 117), s["bar_px"],
                                    self.prev_price, save_path=pic)
            if pr["가격"] is None:
                it["실패이유"] = pr["실패이유"]; it["next_try"] = now + self.retry_sec
                print(f"  [{it['h']['이름']} 뒤] 기록 #{it['rid']}: 현재가 읽기 실패, {self.retry_sec}초 뒤 다시 ({pr['실패이유']})")
                continue
            self.prev_price = pr["가격"]
            chg = self._write(it, now, "읽음", pr["가격"], pr["출처"], pic=pr.get("사진") or "")
            ctext = f"변화 {chg:+.2f}" if chg is not None else "p0가 없어 변화 계산 못 함"
            print(f"  [{it['h']['이름']} 뒤] 기록 #{it['rid']}: 현재가 {pr['가격']} ({ctext}, {round(late)}초 늦게)")
            del self.pending[key]

def load_horizons(cfg, test_spec=None):
    """config의 horizons(분 단위) 또는 시험용 '이름:초:기준폭,…'"""
    if test_spec:
        out = []
        for part in test_spec.split(","):
            n, sec, thr = part.split(":"); out.append({"이름": n, "초": float(sec), "기준폭": float(thr)})
        return out
    return [dict(h, 초=h["분"] * 60) for h in cfg.get("horizons", DEFAULT_HORIZONS)]

def main():
    ap = argparse.ArgumentParser(description="실전 기록: 단축키로 내 판단 기록 (AI 판정은 보여 주지 않음)")
    ap.add_argument("--log-dir", type=Path, default=C.ROOT / "logs")
    ap.add_argument("--hotkey", help="단축키 (기본: config의 hotkey, Ctrl+Alt+J)")
    ap.add_argument("--auto-choice", choices=CHOICES + PAST_CHOICES, help="(시험용) 선택 창에서 자동으로 이것을 고름")
    ap.add_argument("--auto-mode", choices=[NOW, PAST], default=NOW, help="(시험용) 자동 선택 때 차트시점")
    ap.add_argument("--once", action="store_true", help="(시험용) 한 번 기록하고 끝냄 (--test-horizons와 함께면 가격까지 다 읽고 끝냄)")
    ap.add_argument("--test-horizons", help="(시험용) '이름:초:기준폭,…' 예: 20초:20:5,40초:40:5")
    ap.add_argument("--retry-sec", type=float, default=30, help="현재가 읽기 실패 시 다시 시도 간격(초)")
    args = ap.parse_args()
    try: sys.stdout.reconfigure(line_buffering=True)         # 안내 문구가 바로 보이게
    except Exception: pass

    import tkinter as tk
    cfg = C.load_config()
    for k, v in LIVE_DEFAULTS.items(): cfg.setdefault(k, v)
    hotkey = args.hotkey or cfg["hotkey"]
    if not C.chart_region(cfg, C.BIG):
        sys.exit("큰 봉 차트 영역이 없습니다. 먼저 setup_region.py를 실행하세요.")
    s = J.settings(cfg)
    md = Path(s["models_dir"]); md = md if md.is_absolute() else C.ROOT / md
    judge = J.Judge(md)
    tags = {"dir3": RP.model_tag(md, "dir3"), "cls11": RP.model_tag(md, "cls11")}
    base = args.log_dir / "실전기록"

    q, ready = queue.Queue(), queue.Queue()
    threading.Thread(target=hotkey_thread, args=(hotkey, q, ready), daemon=True).start()
    if not ready.get(timeout=5):
        sys.exit(f"단축키 {hotkey}를 등록하지 못했습니다. 다른 프로그램이 이미 쓰고 있을 수 있습니다. "
                 f"--hotkey Ctrl+Alt+K 처럼 바꿔 보세요.")
    root = tk.Tk(); root.withdraw()
    pos = choice_position(cfg, 620, 300)
    horizons = load_horizons(cfg, args.test_horizons)
    ensure_columns(base / "내판단.csv", MY_COLUMNS)          # 예전 기록 파일에 새 열(큰봉분봉, 차트시점, 실제결과) 더하기
    sched = PriceScheduler(cfg, base, horizons, args.retry_sec)
    n_re = sched.rebuild()
    print(f"실전 기록 대기 중: {hotkey}를 누르면 기록합니다 (HTS가 앞에 있어도 됨). 끝내려면 이 터미널에서 Ctrl+C.")
    print("가격 확인: " + ", ".join(f"{h['이름']} 뒤(기준 {h['기준폭']:g}포인트)" for h in horizons)
          + f" — 이 프로그램이 켜져 있어야 읽습니다." + (f" 이전 기록에서 다시 잡은 것 {n_re}개." if n_re else ""))
    print("run_poc.py가 켜져 있으면 AI 판정이 보이니 꺼 두세요. 마우스는 큰 봉 차트 밖에 두면 현재가를 더 잘 읽습니다.")
    state = {"busy": False, "n": 0, "last_tick": 0, "tf": last_timeframe(base)}

    def handle(t_press):
        state["busy"] = True
        try:
            when = datetime.fromtimestamp(t_press); rid = C.stamp(when)
            row, warn = capture_all(cfg, judge, tags, args.log_dir, rid, when, sched.prev_price)
            if row["현재가"] != "" and row["현재가_출처"] == "두 곳 일치": sched.prev_price = row["현재가"]
            price_text = f"{row['현재가']} [{row['현재가_출처']}]" if row["현재가"] != "" else f"읽기 실패 ({row['현재가_실패이유']})"
            for w in warn: print("  ⚠", w)
            mode, choice, memo, tf = ask_choice(root, pos, rid, price_text, args.auto_choice, state["tf"], args.auto_mode)
            state["tf"] = tf
            row.update(차트시점=mode, 내판단=choice if mode == NOW else "", 실제결과=choice if mode == PAST else "",
                       큰봉분봉=tf, 메모=memo, 선택까지_초=round(time.time() - t_press, 1))
            RP.append_rows(base / "내판단.csv", MY_COLUMNS, [row])
            state["n"] += 1
            if mode == NOW and choice in CHOICES:
                sched.add(rid, t_press, row["현재가"] if row["현재가"] != "" else None)
            if mode == PAST:
                print(f"{when:%H:%M:%S} 기록 #{rid} 저장: [과거 차트] 실제 결과 {choice} [큰 봉 {tf}]"
                      + (f" (메모: {memo})" if memo else "") + " — 가격 확인 예약 안 함")
            else:
                print(f"{when:%H:%M:%S} 기록 #{rid} 저장: {choice} [큰 봉 {tf}]" + (f" (메모: {memo})" if memo else "") + f", 현재가 {price_text}")
        except Exception as e:
            print("오류:", e)
        finally:
            state["busy"] = False
            while not q.empty(): q.get_nowait()            # 처리하는 동안 눌린 단축키는 버림 (중복 기록 방지)
        if args.once and not args.test_horizons: root.quit()

    def poll():
        try:
            t = q.get_nowait()
            if not state["busy"]: handle(t)
        except queue.Empty:
            pass
        if not state["busy"] and time.time() - state["last_tick"] >= 5:      # 5초마다 예정 시각 확인
            state["last_tick"] = time.time()
            try: sched.tick()
            except Exception as e: print("가격 확인 오류:", e)
            if args.once and args.test_horizons and state["n"] and not sched.pending:
                root.quit(); return
        root.after(100, poll)
    root.after(100, poll)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    print(f"끝: 이번에 {state['n']}건 기록")

if __name__ == "__main__":
    main()
