"""
4) 분봉별 시험: 300분봉으로 학습한 AI가 다른 분봉에서도 같은 패턴을 알아보는지

"패턴은 300분·10분·1분 등 분봉과 상관없이 비슷하게 나타난다(사용자의 다년간 매매 경험).
 이 PoC는 300분봉으로 학습한 AI가 다른 분봉에서도 같은 패턴을 알아보는지를 시험으로 확인한다."

순서
1. 사진 찍기:   python code/poc/capture_test.py 10분   (분봉마다, data/시험용_분봉/<분봉>/)
2. 정답표 만들기: python code/poc/evaluate_timeframe.py --make-sheet
   → data/시험용_분봉/정답적기_<시각>/ : 01.png… (모든 분봉을 섞은 순서, 이름에 분봉 없음, 회색 점선 = 150봉 창 시작),
      정답표.csv (번호·정답 칸만), _매핑.csv (번호 → 분봉·파일, 채점용)
3. 정답 적기: 그 폴더의 사진만 보고 상승 / 하락 / 없음. 판정은 아직 아무 데도 없다 (이 순서에서는 모델을 돌리지 않았음).
4. 채점:        python code/poc/evaluate_timeframe.py      → 진행기록/시험결과/분봉시험_<시각>.md, .json
   이때 처음으로 PoC 판정(run_poc와 같은 함수, 큰 봉 차트 설정)을 돌려 분봉별로 따로 채점한다.
"""
import argparse, csv, json, random, shutil, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preprocess as P
import capture as C
import judge as J
import report as RP
import evalcommon as E
from run_poc import labeling_image
from evaluate_practice import chart_report, read_csv

TEST_DIR = C.ROOT / "data" / "시험용_분봉"
VALID = {"상승", "하락", "없음"}

def make_sheet(seed, include_used=False, TEST_DIR=TEST_DIR):
    used = set()
    if not include_used:
        for m in TEST_DIR.glob("정답적기_*/_매핑.csv"):
            used |= {r["파일"] for r in read_csv(m)}
    pics = [p for p in sorted(TEST_DIR.glob("*/*.png")) if not p.parent.name.startswith("정답적기_")]
    pics = [p for p in pics if f"{p.parent.name}/{p.name}" not in used]
    if not pics:
        print("새로 정답을 적을 사진이 없습니다. 먼저 capture_test.py로 찍으세요."); return
    cfg = C.load_config(); s = J.settings(cfg, C.BIG)
    rng = random.Random(seed); rng.shuffle(pics)
    out = TEST_DIR / f"정답적기_{C.stamp()}"; out.mkdir(parents=True)
    with open(out / "정답표.csv", "w", encoding="utf-8-sig", newline="") as f1, \
         open(out / "_매핑.csv", "w", encoding="utf-8-sig", newline="") as f2:
        w1 = csv.DictWriter(f1, fieldnames=["번호", "사진", "정답", "라벨의심", "메모"]); w1.writeheader()
        w2 = csv.DictWriter(f2, fieldnames=["번호", "분봉", "파일"]); w2.writeheader()
        for i, p in enumerate(pics, 1):
            img = P.Image.open(p).convert("RGB")
            lay = J.bar_layout(img)
            wins = J.cut_windows(img, [s["main_bars"]], s["bar_px"], lay) if lay else []
            labeling_image(img, {"windows": wins}, s).save(out / f"{i:02d}.png")    # 판정 없이 점선만
            w1.writerow({"번호": i, "사진": f"{i:02d}.png", "정답": "", "라벨의심": "", "메모": ""})
            w2.writerow({"번호": i, "분봉": p.parent.name, "파일": f"{p.parent.name}/{p.name}"})
    by_tf = {}
    for p in pics: by_tf[p.parent.name] = by_tf.get(p.parent.name, 0) + 1
    print(f"정답 적기 {len(pics)}장 → {out}  (분봉별: {by_tf}, 순서는 섞였고 사진에 분봉·판정은 없음)")
    print("그 폴더의 사진만 보고 정답표.csv '정답' 칸에 상승 / 하락 / 없음. 기준: 회색 점선부터 오른쪽 끝까지의 방향.")

def main():
    ap = argparse.ArgumentParser(description="분봉별 시험 (300분봉으로 학습한 AI가 다른 분봉에서도 통하는지)")
    ap.add_argument("--make-sheet", action="store_true", help="모든 분봉 사진을 섞어 정답 적기 폴더를 만들고 끝냄 (판정 안 함)")
    ap.add_argument("--seed", type=int, help="섞기 난수")
    ap.add_argument("--include-used", action="store_true", help="이전 정답 적기에 쓴 사진도 다시 넣기")
    ap.add_argument("--sheet", help="채점할 정답 적기 폴더 이름 (기본: 가장 최근)")
    ap.add_argument("--dir", type=Path, default=TEST_DIR, help="시험 사진 상위 폴더 (기본 data/시험용_분봉)")
    ap.add_argument("--rule", default="agree")
    ap.add_argument("--out", type=Path, default=C.ROOT / "진행기록" / "시험결과")
    args = ap.parse_args()
    if args.make_sheet:
        make_sheet(args.seed, args.include_used, args.dir); return

    TD = args.dir
    sheets = sorted(TD.glob("정답적기_*"))
    target = (TD / args.sheet) if args.sheet else (sheets[-1] if sheets else None)
    if not target or not target.exists():
        sys.exit("정답 적기 폴더가 없습니다. 먼저 --make-sheet 로 만드세요.")
    idmap = {r["번호"]: r for r in read_csv(target / "_매핑.csv")}
    labels = [dict(r, **idmap[r["번호"]]) for r in read_csv(target / "정답표.csv")]
    filled = [r for r in labels if r["정답"].strip()]
    bad = [r["번호"] for r in filled if r["정답"].strip() not in VALID]
    if bad: sys.exit("정답 칸에는 상승 / 하락 / 없음 만: 번호 " + ", ".join(bad))
    if len(filled) < len(labels): print(f"정답이 빈 {len(labels) - len(filled)}장은 빼고 채점합니다.")
    if not filled: sys.exit("정답이 적힌 사진이 없습니다.")

    cfg = C.load_config(); s = J.settings(cfg, C.BIG)
    md = Path(s["models_dir"]); md = md if md.is_absolute() else C.ROOT / md
    judge = J.Judge(md)
    tags = {"dir3": RP.model_tag(md, "dir3"), "cls11": RP.model_tag(md, "cls11")}
    when = datetime.now()
    per_tf, per_photo, warns = {}, [], []
    for r in filled:
        img = P.Image.open(TD / r["파일"]).convert("RGB")
        res = J.judge_region(img, judge, s)
        if res.get("경고"): warns.append(f"{r['파일']}: " + " / ".join(res["경고"]))
        rows = RP.csv_rows(when, r["파일"], res, s, None, tags, {}, C.BIG)
        r2 = dict(r, 실행ID=r["파일"])
        per_tf.setdefault(r["분봉"], []).append((r2, rows))
        per_photo.append(dict(파일=r["파일"], 분봉=r["분봉"], 정답=r["정답"], 최종판정=res["판정"], 최종방향=res["방향"],
                              창별=[dict(봉=w["bars"], 판정=w["판정"], 방향=w["방향"], dir3=w["dir3"],
                                        dir3_점수=w["dir3_점수"], cls11=w["cls11"], cls11_점수=w["cls11_점수"]) for w in res["windows"]]))
    # 분봉 이름에서 숫자 순서로 (예: 10분 < 60분 < 300분)
    order = sorted(per_tf, key=lambda k: (int("".join(ch for ch in k if ch.isdigit()) or 0), k))
    summary = []
    for tf in order:
        items = per_tf[tf]
        main = [[w for w in ws if int(w["창_봉수"]) == s["main_bars"]] for _, ws in items]
        T = [r["정답"].strip() for r, _ in items]
        d3 = E.acc((m[0]["dir3"], t) for m, t in zip(main, T) if m)
        c11 = E.acc((m[0]["cls11_방향"], t) for m, t in zip(main, T) if m)
        rec = E.summarize(T, [(ws[0]["최종판정"], ws[0]["최종방향"] or None) for _, ws in items])
        summary.append((tf, len(items), d3, c11, rec))
    stamp = C.stamp(when); args.out.mkdir(parents=True, exist_ok=True)
    L = [f"# 분봉별 시험 결과 ({when:%Y-%m-%d %H:%M})", "",
         "> 패턴은 300분·10분·1분 등 분봉과 상관없이 비슷하게 나타난다(사용자의 다년간 매매 경험). "
         "이 PoC는 300분봉으로 학습한 AI가 다른 분봉에서도 같은 패턴을 알아보는지를 시험으로 확인한다.", "",
         f"- 정답 적기 폴더: `{target.name}` — 사람이 판정을 보지 않고, 분봉도 모른 채(섞인 순서) 적은 정답",
         f"- 모델: {tags['dir3']} / {tags['cls11']} (300분봉 원본캡처로 학습)",
         f"- 판정: run_poc와 같은 함수, 큰 봉 차트 설정 (봉 간격 {s['bar_px']}px, 창 {s['window_bars']}봉, 규칙 {s['rule']}, "
         f"최소값 {s['min_dir3_score']}, 창 묶기 {s['window_combine']} 기준 {s['main_bars']}봉)",
         "- 정답 기준: 회색 점선(150봉 창 시작)부터 오른쪽 끝까지의 방향", "",
         "## 1. 분봉별 요약", "",
         f"| 분봉 | 사진 수 | 3분류 방향 정답률 ({s['main_bars']}봉 창) | 11분류 방향 정답률 | 알림 수 | 알림 정확도 | 위험한 알림 | 반대 알림 | 애매 |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for tf, n, d3, c11, rec in summary:
        L.append(f"| {tf} | {n} | {E.pct(d3)} | {E.pct(c11)} | {rec['알림수']} | {E.pct(rec['알림정확도'])} ({rec['알림_맞음']}/{rec['알림수']}) | "
                 f"{rec['위험한알림']} | {rec['반대알림']} | {rec['애매수']} |")
    L += ["", "- 300분봉 사진이 있으면 그 줄이 기준이다. 다른 분봉이 300분봉과 비슷하면 '분봉과 상관없이 통한다'는 쪽, 많이 낮으면 아니라는 쪽 근거가 된다.",
          "- 분봉마다 사진이 30장 안팎이라 몇 장 차이로 %가 크게 움직인다. 차이가 작으면 '구분되지 않음'으로 본다.", ""]
    js = dict(시각=when.isoformat(timespec="seconds"), 정답적기=target.name, 모델=tags, 설정=s, 분봉별={}, 사진별=per_photo, 경고=warns)
    for tf in order:
        lines, j = chart_report(f"{tf} (큰 봉)", per_tf[tf], args.rule, s["main_bars"])
        L += lines + [""]; js["분봉별"][tf] = j
    if warns:
        L += ["## 판정 때 나온 경고", ""] + [f"- {w}" for w in warns]
    out_md = args.out / f"분봉시험_{stamp}.md"
    out_md.write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / f"분봉시험_{stamp}.json").write_text(json.dumps(js, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("\n".join(L[:12 + len(summary)]) + f"\n...\n저장: {out_md}")

if __name__ == "__main__":
    main()
