"""
5단계 시험 ①: 모델 시험 — data/시험용/<패턴>/ 사진(학습에 쓰지 않은 새 사진)으로 채점

실행:  python code/poc/evaluate_model.py
결과:  진행기록/시험결과/모델시험_<시각>.md (사람이 읽는 표), .json (모든 점수, 반올림 없음)

비교하는 것
- 방향: 3분류, 11분류(방향으로 바꿈), 규칙 코드(AI 없음), 늘 "상승" 찍기
- 패턴: 11분류, 규칙 코드
- 알림 규칙: 두 모델이 같을 때만 알림(agree), 3분류만(dir3_only) × 3분류 점수 최소값 0.0–0.9
- 성공 기준 ①: 시험 사진 30장 이상에서 방향 80% 이상

지켜야 할 것 (CLAUDE.md "평가 원칙")
- 시험용 사진의 정답(폴더)은 모델을 돌리기 전에 정한다. 결과를 보고 정답을 고치지 않는다.
- 라벨이 의심되는 사진은 data/시험용/라벨의심.csv 에 "파일,메모"로 적는다. 점수는 원래 정답으로 매기고, 목록은 따로 보여 준다.
- 시험이 끝난 사진만 학습용으로 옮긴다 (진행기록/04).
"""
import argparse, json, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preprocess as P
import capture as C
import judge as J
import rules as R
import report as RP
import rule_baseline as RB
import evalcommon as E

def main():
    ap = argparse.ArgumentParser(description="시험용 사진으로 모델 채점")
    ap.add_argument("--data", type=Path, default=C.ROOT / "data" / "시험용")
    ap.add_argument("--suspects", type=Path, help="라벨 의심 목록 CSV (기본: <data>/라벨의심.csv)")
    ap.add_argument("--out", type=Path, default=C.ROOT / "진행기록" / "시험결과")
    args = ap.parse_args()
    sus_path = args.suspects or args.data / "라벨의심.csv"
    if not sus_path.exists():
        sus_path.parent.mkdir(parents=True, exist_ok=True)
        sus_path.write_text("파일,메모\n", encoding="utf-8-sig")
        print(f"라벨 의심 목록 빈 양식을 만들었습니다: {sus_path}")
    suspects = E.read_label_suspects(sus_path)

    items = [(f, c) for c in P.CLASSES for f in sorted((args.data / c).glob("*.png"))]
    if not items:
        print(f"{args.data} 에 사진이 없습니다. 새 캡처를 data/시험용/<패턴>/ 에 넣은 뒤 다시 실행하세요.")
        return
    s = J.settings(C.load_config())
    md = Path(s["models_dir"]); md = md if md.is_absolute() else C.ROOT / md
    judge = J.Judge(md)
    tags = {"dir3": RP.model_tag(md, "dir3"), "cls11": RP.model_tag(md, "cls11")}

    rows = []
    for f, c in items:
        img = P.prepare(P.Image.open(f))
        r = judge(img)
        rb = RB.predict(img)
        rel = str(f.relative_to(args.data)).replace("\\", "/")
        rows.append(dict(파일=rel, 정답=c, 정답방향=P.direction(c), dir3=r["dir3"], dir3_점수=r["dir3_점수"],
                         cls11=r["cls11"], cls11_방향=r["cls11_방향"], cls11_점수=r["cls11_점수"],
                         규칙코드=rb, 규칙코드_방향=P.direction(rb), 라벨의심=suspects.get(rel, suspects.get(f.name))))
    T = [r["정답방향"] for r in rows]
    n = len(rows)
    direction = {
        "3분류": E.acc((r["dir3"], r["정답방향"]) for r in rows),
        "11분류": E.acc((r["cls11_방향"], r["정답방향"]) for r in rows),
        "규칙 코드": E.acc((r["규칙코드_방향"], r["정답방향"]) for r in rows),
        "늘 상승 찍기": E.acc(("상승", r["정답방향"]) for r in rows),
    }
    pattern = {"11분류": E.acc((r["cls11"], r["정답"]) for r in rows), "규칙 코드": E.acc((r["규칙코드"], r["정답"]) for r in rows)}
    sweeps = {}
    for rule in ("agree", "dir3_only"):
        sweeps[rule] = [(t, E.summarize(T, [R.decide(r["dir3"], r["cls11_방향"], rule, r["dir3_점수"][r["dir3"]], t) for r in rows]))
                        for t in E.THRESHOLDS]

    when = datetime.now(); stamp = C.stamp(when)
    args.out.mkdir(parents=True, exist_ok=True)
    L = [f"# 모델 시험 결과 ({when:%Y-%m-%d %H:%M})", "",
         f"- 시험 사진: `{args.data}` {n}장 (방향별: " + ", ".join(f"{d} {T.count(d)}" for d in P.DIRS) + ")",
         f"- 모델: {tags['dir3']} / {tags['cls11']}",
         f"- 현재 설정: 규칙 {s['rule']}, 3분류 점수 최소값 {s['min_dir3_score']}",
         "- 점수는 확률이 아니다. 표의 %는 사람이 읽기 쉽게 반올림한 것이고, 모든 점수 원본은 같은 이름의 .json에 있다.", "",
         "## 1. 방향 정답률", "", "| 방법 | 방향 정답률 |", "| --- | --- |"]
    L += [f"| {k} | {E.pct(v)} |" for k, v in direction.items()]
    ok30 = n >= 30
    L += ["", f"**성공 기준 ① (시험 사진 30장 이상, 방향 80% 이상):** 사진 {n}장 → "
          + ("판단 가능" if ok30 else "**30장 미만이라 판단 보류**")
          + (f", 3분류 {E.pct(direction['3분류'])} → {'통과' if direction['3분류'] >= 0.8 else '미달'}" if ok30 else ""), "",
          "## 2. 패턴 정답률 (참고)", "", "| 방법 | 패턴 정답률 |", "| --- | --- |"]
    L += [f"| {k} | {E.pct(v)} |" for k, v in pattern.items()]
    for rule, title in (("agree", "두 모델이 같을 때만 알림 (agree)"), ("dir3_only", "3분류만 보고 알림 (dir3_only, 비교용)")):
        L += ["", f"## 3. 알림 규칙: {title} — 3분류 점수 최소값을 바꿔 보기", "", E.sweep_table(sweeps[rule])]
    L += ["", "- 알림 정확도: 알림 중 방향이 맞은 비율 / 알림 적중: 방향이 있는 사진 중 맞게 알린 비율",
          "- 위험한 알림: 정답이 '없음'인데 상승·하락을 알림 / 반대 알림: 정답과 반대 방향으로 알림",
          "- 기준값은 이 표를 보고 사용자가 정한다 (알림 수가 너무 줄지 않으면서 위험한·반대 알림이 줄어드는 값).", "",
          "## 4. 사진별 결과", "",
          "| 파일 | 정답 | 3분류 (점수) | 11분류 (점수) | 규칙 코드 | agree 판정 (최소값 0) | 라벨 의심 |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        j, d = R.decide(r["dir3"], r["cls11_방향"], "agree")
        mark = "" if r["dir3"] == r["정답방향"] else " ✗"
        L.append(f"| {r['파일']} | {r['정답']}({r['정답방향']}) | {r['dir3']} ({r['dir3_점수'][r['dir3']]:.3f}){mark} | "
                 f"{r['cls11']} ({r['cls11_점수'][r['cls11']]:.3f}) | {r['규칙코드']} | {j}{'(' + d + ')' if j == R.ALERT else ''} | "
                 f"{'⚑ ' + (r['라벨의심'] or '') if r['라벨의심'] is not None else ''} |")
    sus_rows = [r for r in rows if r["라벨의심"] is not None]
    L += ["", "## 5. 라벨 의심 사진 (정답은 고치지 않았고, 위 점수는 원래 정답으로 매김)", ""]
    L += [f"- {r['파일']} (정답 {r['정답']}): {r['라벨의심'] or '메모 없음'}" for r in sus_rows] or ["- 없음"]
    out_md = args.out / f"모델시험_{stamp}.md"
    out_md.write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / f"모델시험_{stamp}.json").write_text(json.dumps(dict(
        시각=when.isoformat(timespec="seconds"), 시험폴더=str(args.data), 모델=tags, 설정=s,
        방향정답률=direction, 패턴정답률=pattern, 알림규칙_기준값별={k: [dict(기준값=t, **v) for t, v in sw] for k, sw in sweeps.items()},
        사진별=rows), ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(L[:20]))
    print(f"...\n저장: {out_md}")

if __name__ == "__main__":
    main()
