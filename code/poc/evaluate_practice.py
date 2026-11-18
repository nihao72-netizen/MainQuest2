"""
5단계 시험 ②: PoC 실전 시험 — run_poc.py가 실제 화면에서 판정한 결과를, 사람이 나중에 적은 정답과 비교
화면 위 "큰 봉" 차트와 아래 "작은 봉" 차트를 따로 채점한다.

순서
1. run_poc.py를 평소처럼 돌린다. 판정할 때마다 차트별로 아래 두 가지가 자동으로 생긴다.
   - logs/실전시험/사진/<실행ID>_<큰봉|작은봉>.png : 결과 글자·색이 없는 깨끗한 차트 (회색 점선 = 기준 창 시작)
   - logs/실전시험/정답표.csv                       : 실행ID, 차트, 시각, 사진, 정답(빈칸), 라벨의심, 메모 — 판정 결과는 없음
2. 표본 정답표를 만든다 (권장):  python code/poc/evaluate_practice.py --make-sample
3. 표본 폴더의 사진만 보고 '정답' 칸에 상승 / 하락 / 없음 을 적는다.
   - 정답을 다 적기 전에는 logs/판정기록*.csv, logs/images/ 를 열지 않는다 (판정을 보면 정답이 흔들림).
   - 애매하면 정답을 적고 '라벨의심' 칸에 O, 이유는 '메모'에. 점수는 적은 정답으로 매기고, 의심 목록은 따로 보여 준다.
4. 정답을 다 적은 뒤:  python code/poc/evaluate_practice.py   → 진행기록/시험결과/실전시험_<시각>.md, .json

표본 정답표
  5분마다 찍은 판정 사진은 차트가 거의 변하지 않아 사실상 같은 문제다. 그대로 채점하면 같은 문제를
  여러 번 센 것이 되어 점수가 실제보다 확실해 보인다. 그래서 서로 충분히 떨어진 사진만 골라 순서를 섞어 정답을 적는다.
  python code/poc/evaluate_practice.py --make-sample                      (기본: 차트마다 서로 3시간 이상, 40장)
  python code/poc/evaluate_practice.py --make-sample --min-gap-hours 24 --count 30 --chart 큰봉
  → logs/실전시험/표본_<시각>/ : 01.png… (섞인 순서, 이름에 시각·차트 없음), 정답표.csv(번호·차트·정답 칸), _매핑.csv(번호→실행ID)
  정답을 다 적은 뒤 그냥 실행하면 가장 최근 표본으로 채점한다 (--sheet 로 다른 표본·전체 정답표 지정 가능).

다른 사용법
  python code/poc/evaluate_practice.py --sync     전체 정답표에 빠진 사진 줄만 채움 (판정 결과는 보여 주지 않음)
"""
import argparse, csv, json, random, shutil, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture as C
import rules as R
import evalcommon as E
from run_poc import LABEL_COLUMNS, migrate_label_sheet

VALID = {"상승", "하락", "없음"}
SAMPLE_COLUMNS = ["번호", "차트", "사진", "정답", "라벨의심", "메모"]
FILE_TO_CHART = {v: k for k, v in C.CHART_FILE.items()}

def read_csv(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def parse_photo(p):
    """'<실행ID>_<큰봉|작은봉>.png' → (실행ID, 차트). 예전 이름 '<실행ID>.png'은 큰 봉"""
    stem = p.stem
    rid, _, tail = stem[:15], stem[15:16], stem[16:]
    chart = FILE_TO_CHART.get(tail.split("_")[0], C.BIG) if tail else C.BIG
    return rid, chart

def _rid_time(rid):
    return datetime.strptime(rid[:15], "%Y%m%d_%H%M%S")

def sync(base):
    """사진 폴더에는 있는데 전체 정답표에 없는 줄을 추가 (기존 줄은 건드리지 않음)"""
    sheet = base / "정답표.csv"
    migrate_label_sheet(sheet)
    rows = read_csv(sheet) if sheet.exists() else []
    have = {(r["실행ID"], r["차트"]) for r in rows}
    add = []
    for p in sorted((base / "사진").glob("*.png")):
        try: rid, chart = parse_photo(p); when = _rid_time(rid).isoformat()
        except ValueError: continue
        if (rid, chart) not in have:
            add.append({"실행ID": rid, "차트": chart, "시각": when, "사진": f"사진/{p.name}", "정답": "", "라벨의심": "", "메모": ""})
    if add:
        new = not sheet.exists()
        with open(sheet, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=LABEL_COLUMNS)
            if new: wr.writeheader()
            wr.writerows(add)
    print(f"정답표: 기존 {len(rows)}줄, 추가 {len(add)}줄 → {sheet}")
    print("정답 칸에 상승 / 하락 / 없음 을 적으세요. 다 적기 전에는 판정기록.csv와 images 폴더를 열지 마세요.")

def make_sample(base, min_gap_hours, count, seed, charts, exclude_used=True):
    """차트마다 서로 min_gap_hours 이상 떨어진 사진만 골라 count장씩, 순서를 섞어 새 표본 폴더를 만든다 (판정 결과는 넣지 않음)"""
    used = set()
    if exclude_used:
        for m in base.glob("표본_*/_매핑.csv"):
            used |= {(r["실행ID"], r.get("차트") or C.BIG) for r in read_csv(m)}
    by_chart = defaultdict(list)
    for p in sorted((base / "사진").glob("*.png")):
        try: rid, chart = parse_photo(p); t = _rid_time(rid)
        except ValueError: continue
        if chart in charts and (rid, chart) not in used:
            by_chart[chart].append((t, rid, p))
    rng = random.Random(seed)
    picked, report = [], []
    for chart in charts:
        cand = sorted(by_chart[chart])
        # 1) 시간 순서로 보면서 직전에 고른 사진과 min_gap 이상 떨어진 것만 → 간격을 지키는 가장 많은 장수
        spaced = []
        for item in cand:
            if not spaced or (item[0] - spaced[-1][0]).total_seconds() >= min_gap_hours * 3600:
                spaced.append(item)
        # 2) 그보다 많으면 무작위로 count장 (골라도 서로의 간격은 그대로 min_gap 이상)
        got = rng.sample(spaced, count) if len(spaced) > count else spaced
        picked += [(chart, *g) for g in got]
        times = sorted(g[0] for g in got)
        gaps = [(b - a).total_seconds() / 3600 for a, b in zip(times, times[1:])]
        report.append((chart, len(got), len(cand), min(gaps) if gaps else None))
    if not picked:
        print(f"고를 사진이 없습니다 (이전 표본에서 쓴 사진 {len(used)}장 제외)."); return None
    rng.shuffle(picked)                              # 정답 적는 순서도 섞음 (차트도 섞임)
    out = base / f"표본_{C.stamp()}"
    out.mkdir(parents=True)
    with open(out / "정답표.csv", "w", encoding="utf-8-sig", newline="") as f1, \
         open(out / "_매핑.csv", "w", encoding="utf-8-sig", newline="") as f2:
        w1 = csv.DictWriter(f1, fieldnames=SAMPLE_COLUMNS); w1.writeheader()
        w2 = csv.DictWriter(f2, fieldnames=["번호", "실행ID", "차트"]); w2.writeheader()
        for i, (chart, t, rid, p) in enumerate(picked, 1):
            name = f"{i:02d}.png"
            shutil.copy2(p, out / name)
            w1.writerow({"번호": i, "차트": chart, "사진": name, "정답": "", "라벨의심": "", "메모": ""})
            w2.writerow({"번호": i, "실행ID": rid, "차트": chart})
    print(f"표본 {len(picked)}장 → {out}")
    for chart, n, total, g in report:
        line = f"  {chart}: {n}장 (후보 {total}장)"
        if g is not None: line += f", 고른 사진끼리 가장 가까운 간격 {g:.1f}시간"
        if n < count: line += f"  ⚠ 목표 {count}장보다 적음 (서로 {min_gap_hours}시간 이상 떨어진 사진이 부족)"
        print(line)
    print("  참고: 간격이 짧으면 차트 그림이 거의 같다. 봉 하나가 몇 시간짜리인지에 따라 다르다 —\n"
          "  예를 들어 봉 하나가 5시간이면 3시간 간격으로는 새 봉이 1개도 생기지 않아 150봉 창이 거의 그대로다.")
    print("  이 폴더의 사진만 보고 정답표.csv의 '정답' 칸에 상승 / 하락 / 없음 을 적으세요. 순서는 이미 섞여 있습니다.")
    return out

def load_sheet(base, sheet_arg):
    """채점할 정답표 → [{'실행ID','차트','정답','라벨의심','메모'}], 설명. 기본: 가장 최근 표본, 없으면 전체 정답표"""
    if sheet_arg:
        target = Path(sheet_arg)
        if not target.is_absolute(): target = base / target
    else:
        samples = sorted(base.glob("표본_*"))
        target = samples[-1] if samples else base / "정답표.csv"
    if target.is_dir():
        idmap = {r["번호"]: (r["실행ID"], r.get("차트") or C.BIG) for r in read_csv(target / "_매핑.csv")}
        rows = [dict(r, 실행ID=idmap[r["번호"]][0], 차트=idmap[r["번호"]][1]) for r in read_csv(target / "정답표.csv")]
        return rows, f"표본 `{target.name}` ({len(rows)}장, 서로 떨어진 사진만, 섞인 순서)"
    if not target.exists():
        sys.exit(f"정답표가 없습니다: {target}\nrun_poc.py를 먼저 돌리거나 --sync / --make-sample 로 만드세요.")
    migrate_label_sheet(target)
    rows = read_csv(target)
    return rows, (f"전체 정답표 `{target.name}` ({len(rows)}줄) — 연달아 찍은 판정이 섞여 있어 같은 문제를 여러 번 센 것일 수 있음. "
                  "표본(--make-sample)으로 채점하는 것을 권장")

def load_runs(log_dir):
    """판정기록*.csv (열 구성이 바뀌어 _v2 등으로 나뉜 파일 포함) → (실행ID, 차트)별 창 목록. 차트 열이 없는 예전 기록은 큰 봉"""
    runs = defaultdict(list)
    for p in sorted(log_dir.glob("판정기록*.csv")):
        for r in read_csv(p):
            if r.get("창_봉수"):
                runs[(r["실행ID"], r.get("차트") or C.BIG)].append(r)
    return runs

def decide_windows(wrows, rule, t):
    wins = []
    for r in wrows:
        dir3 = r["dir3"]; score = float(r[f"dir3_점수_{dir3}"])
        j, d = R.decide(dir3, r["cls11_방향"], rule, score, t)
        wins.append(dict(bars=int(r["창_봉수"]), 판정=j, 방향=d))
    return sorted(wins, key=lambda w: w["bars"])

def chart_report(chart, items, rule, main_bars):
    """차트 하나의 채점 → (마크다운 줄들, json용 dict)"""
    T = [r["정답"].strip() for r, _ in items]
    bars_list = sorted({int(w["창_봉수"]) for _, ws in items for w in ws})
    combos = {how: [(t, E.summarize(T, [R.combine(decide_windows(ws, rule, t), how, main_bars)[:2] for _, ws in items]))
                    for t in E.THRESHOLDS] for how in R.COMBINES}
    per_win = {}
    for b in bars_list:
        sub = [(r["정답"].strip(), [w for w in ws if int(w["창_봉수"]) == b]) for r, ws in items]
        sub = [(t, w[0]) for t, w in sub if w]
        per_win[b] = dict(
            사진수=len(sub),
            dir3_방향정답률=E.acc((w["dir3"], t) for t, w in sub),
            cls11_방향정답률=E.acc((w["cls11_방향"], t) for t, w in sub),
            agree_최소값0=E.summarize([t for t, _ in sub], [R.decide(w["dir3"], w["cls11_방향"], rule) for _, w in sub]))
    recorded = E.summarize(T, [(ws[0]["최종판정"], ws[0]["최종방향"] or None) for _, ws in items])
    settings_used = sorted({(ws[0].get("설정_rule", ""), ws[0].get("설정_min_dir3_score", "0"), ws[0].get("설정_window_combine", ""),
                             ws[0].get("설정_main_bars", ""), ws[0].get("설정_window_bars", ""), ws[0].get("모델_dir3", "")) for _, ws in items})
    suspects = [(r, ws) for r, ws in items if r["라벨의심"].strip()]
    L = [f"## {chart} 차트 — 판정 {len(items)}회 (방향별: " + ", ".join(f"{d} {T.count(d)}" for d in ("상승", "하락", "없음")) + ")", "",
         "### 그때 실제로 쓴 설정의 결과", "",
         f"- 알림 {recorded['알림수']}번 중 {recorded['알림_맞음']}번 맞음 ({E.pct(recorded['알림정확도'])}), "
         f"위험한 알림 {recorded['위험한알림']}번, 반대 알림 {recorded['반대알림']}번, 애매 {recorded['애매수']}번, 없음 {recorded['없음판정수']}번",
         "- 쓴 설정 (규칙, 최소값, 창 묶기, 기준 창, 창 폭, 모델): " + "; ".join(" / ".join(map(str, x)) for x in settings_used), "",
         "### 창 폭별 (그 창 하나만 썼다면)", "",
         "| 창 | 판정 수 | 3분류 방향 정답률 | 11분류 방향 정답률 | agree 알림 정확도 | 알림 적중 | 위험한 알림 |",
         "| --- | --- | --- | --- | --- | --- | --- |"]
    for b, v in per_win.items():
        a = v["agree_최소값0"]
        L.append(f"| {b}봉 | {v['사진수']} | {E.pct(v['dir3_방향정답률'])} | {E.pct(v['cls11_방향정답률'])} | "
                 f"{E.pct(a['알림정확도'])} ({a['알림_맞음']}/{a['알림수']}) | {E.pct(a['알림적중'])} | {a['위험한알림']} |")
    names = {"main": f"main ({main_bars}봉 창 기준)", "all_agree": "all_agree (모든 창이 같을 때만)", "majority": "majority (과반)"}
    for how in R.COMBINES:
        L += ["", f"### 창 묶기 {names[how]} — 3분류 점수 최소값을 바꿔 보기", "", E.sweep_table(combos[how])]
    L += ["", "### 라벨 의심 (정답은 고치지 않았고, 위 점수는 적은 정답으로 매김)", ""]
    for r, ws in suspects:
        L.append(f"- {r['실행ID']} (정답 {r['정답']}): {r['메모'] or '메모 없음'} — 기록된 최종 판정 {ws[0]['최종판정']}"
                 + (f"({ws[0]['최종방향']})" if ws[0]["최종방향"] else ""))
    if not suspects: L.append("- 없음")
    js = dict(판정수=len(items), 실제설정결과=recorded, 창폭별=per_win,
              창묶기_기준값별={k: [dict(기준값=t, **v) for t, v in sw] for k, sw in combos.items()},
              라벨의심=[r["실행ID"] for r, _ in suspects])
    return L, js

def main():
    ap = argparse.ArgumentParser(description="PoC 실전 시험 채점 (큰 봉·작은 봉 차트 따로)")
    ap.add_argument("--log-dir", type=Path, default=C.ROOT / "logs")
    ap.add_argument("--sync", action="store_true", help="전체 정답표에 빠진 사진 줄만 채우고 끝냄 (판정 결과는 보여 주지 않음)")
    ap.add_argument("--make-sample", action="store_true", help="서로 떨어진 사진만 골라 섞은 표본 정답표를 만들고 끝냄")
    ap.add_argument("--min-gap-hours", type=float, default=3.0, help="표본 사진끼리 최소 간격(시간). 기본 3")
    ap.add_argument("--count", type=int, default=40, help="차트마다 표본 사진 수. 기본 40")
    ap.add_argument("--chart", default="큰봉,작은봉", help="표본을 만들 차트 (쉼표로). 기본 둘 다")
    ap.add_argument("--seed", type=int, help="표본 고르기·섞기 난수 (같은 값이면 같은 표본)")
    ap.add_argument("--include-used", action="store_true", help="이전 표본에 쓴 사진도 다시 고를 수 있게")
    ap.add_argument("--sheet", help="채점할 정답표: 표본 폴더 이름(표본_…) 또는 정답표.csv. 기본: 가장 최근 표본")
    ap.add_argument("--rule", default="agree")
    ap.add_argument("--main-bars", type=int, default=150)
    ap.add_argument("--out", type=Path, default=C.ROOT / "진행기록" / "시험결과")
    args = ap.parse_args()
    base = args.log_dir / "실전시험"
    if args.sync:
        sync(base); return
    if args.make_sample:
        charts = [C.chart_name(x) for x in args.chart.split(",") if x.strip()]
        make_sample(base, args.min_gap_hours, args.count, args.seed, charts, not args.include_used); return

    labels, sheet_desc = load_sheet(base, args.sheet)
    print("채점할 정답표:", sheet_desc)
    filled = [r for r in labels if r["정답"].strip()]
    bad = [r for r in filled if r["정답"].strip() not in VALID]
    empty = len(labels) - len(filled)
    if bad:
        sys.exit("정답 칸에는 상승 / 하락 / 없음 만 적을 수 있습니다. 확인할 줄: " + ", ".join(r.get("번호") or r["실행ID"] for r in bad))
    if empty:
        print(f"아직 정답이 빈 줄 {empty}개는 빼고 채점합니다.")
    runs = load_runs(args.log_dir)
    key = lambda r: (r["실행ID"], r.get("차트") or C.BIG)
    items = [(r, runs[key(r)]) for r in filled if runs.get(key(r))]
    missing = [r["실행ID"] for r in filled if not runs.get(key(r))]
    if not items:
        sys.exit("정답이 적힌 줄과 맞는 판정 기록이 없습니다.")

    when = datetime.now(); stamp = C.stamp(when)
    args.out.mkdir(parents=True, exist_ok=True)
    L = [f"# PoC 실전 시험 결과 ({when:%Y-%m-%d %H:%M})", "",
         f"- 채점한 정답표: {sheet_desc}",
         f"- 정답을 적은 판정 {len(items)}회" + (f", 판정 기록을 찾지 못한 줄 {len(missing)}개" if missing else "")
         + (f", 정답이 빈 줄 {empty}개는 제외" if empty else ""),
         f"- 정답 기준: 기준 창({args.main_bars}봉) 시작부터 오른쪽 끝까지의 방향 (사람이 깨끗한 사진만 보고 적음)",
         f"- 다시 계산한 규칙: {args.rule}. 창 묶기·최소값은 기록된 창별 점수로 다시 계산했다.",
         "- 가까운 시각에 찍은 판정은 기준 창의 봉 대부분이 겹쳐 서로 독립된 시험이 아니다. 판정 수가 많아 보여도 실제 정보량은 더 적다.",
         "- 알림 정확도: 알림 중 방향이 맞은 비율 / 알림 적중: 방향이 있는 판정 중 맞게 알린 비율 / "
         "위험한 알림: 정답이 '없음'인데 상승·하락을 알림 / 반대 알림: 정답과 반대 방향으로 알림", ""]
    js = dict(시각=when.isoformat(timespec="seconds"), 정답표=sheet_desc, 규칙=args.rule, 기준창=args.main_bars, 기록없는줄=missing, 차트별={})
    for chart in C.CHART_NAMES:
        sub = [(r, ws) for r, ws in items if key(r)[1] == chart]
        if not sub: continue
        lines, j = chart_report(chart, sub, args.rule, args.main_bars)
        L += lines + [""]; js["차트별"][chart] = j
    out_md = args.out / f"실전시험_{stamp}.md"
    out_md.write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / f"실전시험_{stamp}.json").write_text(json.dumps(js, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(L[:16]) + f"\n...\n저장: {out_md}")

if __name__ == "__main__":
    main()
