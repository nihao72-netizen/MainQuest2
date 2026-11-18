"""
실전 기록 4단계: 결과 표 — 내 판단과 AI 판정을, 정해 둔 시간 뒤 실제 가격 변화와 비교

실행:  python code/poc/evaluate_live.py                         (config의 기준 폭: 30분 20, 2시간 40, 1일 100)
       python code/poc/evaluate_live.py --thr 30분=25,1일=80     (기준 폭만 바꿔 다시 계산)
결과:  진행기록/시험결과/실전기록_<시각>.md, .json

주의: 이 표에는 AI 판정이 나온다. 기록하는 도중에 보면 다음 판단이 AI 쪽으로 기울 수 있으니,
      기록이 충분히 쌓인 뒤(예: 30건 이상) 보는 것을 권장한다.

채점 기준 (시간마다 따로)
- 실제 방향: p1 − p0 ≥ 기준 폭 → 올랐음, ≤ −기준 폭 → 내렸음, 그 사이 → 변동 작음
- 적중률 = 방향을 말한 것(오른다·내린다 / 상승·하락) 중 맞은 비율. "변동 작음"은 틀린 것으로 센다
  (변동 작음을 뺀 비율도 함께 보여 줌)
- 나와 AI가 같을 때 = 내가 오른다·내린다라고 했고, AI도 같은 방향을 말한 기록만
"""
import argparse, csv, json, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture as C
from record_live import DEFAULT_HORIZONS, direction_of

MINE = {"오른다": "상승", "내린다": "하락"}
HIT = {"상승": "올랐음", "하락": "내렸음"}
OPP = {"상승": "내렸음", "하락": "올랐음"}
AI_KINDS = [  # (이름, AI판정.csv에서 방향을 꺼내는 방법)
    ("큰 봉 3분류 (150봉 창)", lambda a: a.get("큰봉_150봉_dir3", "")),
    ("큰 봉 알림 (두 모델 일치)", lambda a: a.get("큰봉_방향", "") if a.get("큰봉_판정") == "알림" else ""),
    ("작은 봉 3분류 (150봉 창)", lambda a: a.get("작은봉_150봉_dir3", "")),
    ("작은 봉 알림 (두 모델 일치)", lambda a: a.get("작은봉_방향", "") if a.get("작은봉_판정") == "알림" else ""),
    ("진입 확인 (큰 봉 = 작은 봉)", lambda a: a.get("진입방향", "") if a.get("진입확인") == "예" else ""),
]

def read_csv(p):
    if not p.exists(): return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

# ---- 숫자 목표 (problem_definition.md 5장 ⑪⑫⑬, 2026-11-18 결과 표를 보기 전에 사용자가 정함) ----
BIG_ALERT = "큰 봉 알림 (두 모델 일치)"
T11_MARGIN, T11_MIN = 0.10, 10   # ⑪ AI 큰 봉 알림 ≥ max(늘 오른다, 늘 내린다) + 10%p, 큰 봉 알림 10건 이상
T12_MARGIN, T12_MIN = 0.10, 10   # ⑫ 같을 때 ≥ 내 판단 + 10%p, 같을 때 10건 이상
T13_TOL, T13_MIN, BASE_TF = 0.15, 10, "300분"   # ⑬ 각 분봉이 300분봉과 15%p 이내, 둘 다 10건 이상
EPS = 1e-9

def judge_targets(r):
    """한 시간(예: 30분 뒤)의 결과 r → ⑪⑫⑬ 판정 목록 [dict(번호, 대상, 값, 기준, 결과, 설명)]"""
    out = []
    ai = r["AI"][BIG_ALERT]; up, dn = r["늘오른다"], r["늘내린다"]
    base = max([x["적중률"] for x in (up, dn) if x["적중률"] is not None], default=None)
    if ai["수"] < T11_MIN or base is None:
        out.append(dict(번호="⑪", 대상="AI 큰 봉 알림 vs 늘 오른다·내린다", 값=f"{pct(ai['적중률'])} ({ai['맞음']}/{ai['수']})",
                        기준=f"큰 봉 알림 {T11_MIN}건 이상 필요", 결과="판단 보류", 설명=f"큰 봉 알림 {ai['수']}건"))
    else:
        need = base + T11_MARGIN
        out.append(dict(번호="⑪", 대상="AI 큰 봉 알림 vs 늘 오른다·내린다", 값=f"{ai['적중률']:.0%} ({ai['맞음']}/{ai['수']})",
                        기준=f"≥ {need:.0%} (높은 쪽 {base:.0%} + 10%p)", 결과="통과" if ai["적중률"] + EPS >= need else "미달",
                        설명=f"차이 {(ai['적중률'] - base) * 100:+.0f}%p"))
    ag, me = r["같을때"][BIG_ALERT], r["내판단"]
    if ag["수"] < T12_MIN or me["적중률"] is None:
        out.append(dict(번호="⑫", 대상="나와 AI(큰 봉 알림)가 같을 때 vs 내 판단", 값=f"{pct(ag['적중률'])} ({ag['맞음']}/{ag['수']})",
                        기준=f"같을 때 {T12_MIN}건 이상 필요", 결과="판단 보류", 설명=f"같을 때 {ag['수']}건"))
    else:
        need = me["적중률"] + T12_MARGIN
        out.append(dict(번호="⑫", 대상="나와 AI(큰 봉 알림)가 같을 때 vs 내 판단", 값=f"{ag['적중률']:.0%} ({ag['맞음']}/{ag['수']})",
                        기준=f"≥ {need:.0%} (내 판단 {me['적중률']:.0%} + 10%p)", 결과="통과" if ag["적중률"] + EPS >= need else "미달",
                        설명=f"차이 {(ag['적중률'] - me['적중률']) * 100:+.0f}%p"))
    by = r["분봉별"]; b = by.get(BASE_TF, {}).get("큰봉알림")
    others = [tf for tf in by if tf not in (BASE_TF, "미입력")]
    if not others:
        out.append(dict(번호="⑬", 대상="분봉별 AI 큰 봉 알림 vs 300분", 값="—", 기준="—", 결과="판단 보류", 설명="300분 말고 다른 분봉 기록 없음"))
    for tf in others:
        s = by[tf]["큰봉알림"]
        if not b or b["수"] < T13_MIN or s["수"] < T13_MIN:
            out.append(dict(번호="⑬", 대상=f"{tf} vs {BASE_TF} (AI 큰 봉 알림)", 값=f"{pct(s['적중률'])} ({s['맞음']}/{s['수']}) vs "
                            f"{pct(b['적중률']) if b else '—'} ({b['맞음'] if b else 0}/{b['수'] if b else 0})",
                            기준=f"둘 다 {T13_MIN}건 이상 필요", 결과="판단 보류", 설명=""))
        else:
            diff = s["적중률"] - b["적중률"]
            out.append(dict(번호="⑬", 대상=f"{tf} vs {BASE_TF} (AI 큰 봉 알림)", 값=f"{s['적중률']:.0%} ({s['맞음']}/{s['수']}) vs "
                            f"{b['적중률']:.0%} ({b['맞음']}/{b['수']})", 기준="차이 15%p 이내",
                            결과="통과" if abs(diff) <= T13_TOL + EPS else "미달", 설명=f"차이 {diff * 100:+.0f}%p"))
    return out

def tf_sort(tf):
    """'10분' < '60분' < '300분' < 기타 < 미입력 순서"""
    digits = "".join(ch for ch in tf if ch.isdigit())
    return (0, int(digits)) if digits else ((1, 0) if tf != "미입력" else (2, 0))

def score(calls):
    """calls: [(예측 방향 상승/하락, 실제 올랐음/내렸음/변동 작음)] → dict"""
    n = len(calls)
    hit = sum(HIT[p] == a for p, a in calls)
    opp = sum(OPP[p] == a for p, a in calls)
    small = sum(a == "변동 작음" for _, a in calls)
    moved = n - small
    return dict(수=n, 맞음=hit, 반대=opp, 변동작음=small,
                적중률=(hit / n) if n else None, 변동작음_뺀_적중률=(hit / moved) if moved else None)

def pct(x): return "—" if x is None else f"{x:.0%}"

def fmt(s):
    if not s["수"]: return "— (0건)"
    return f"{pct(s['적중률'])} ({s['맞음']}/{s['수']}) · 반대 {s['반대']} · 변동 작음 {s['변동작음']} · 변동 작음 뺀 {pct(s['변동작음_뺀_적중률'])}"

def evaluate(base, horizons):
    mine = {r["기록ID"]: r for r in read_csv(base / "내판단.csv")}
    ai = {r["기록ID"]: r for r in read_csv(base / "AI판정.csv")}
    prices = read_csv(base / "가격결과.csv")
    out = {"기록수": {k: sum(r["내판단"] == k for r in mine.values()) for k in ("오른다", "내린다", "모르겠다", "취소")},
           "시간별": {}}
    days = {r["시각"][:10] for r in mine.values() if r["내판단"] in ("오른다", "내린다", "모르겠다")}
    out["기록한_날수"] = len(days)
    out["p0_출처"] = {}
    for r in mine.values():
        if r["내판단"] in ("오른다", "내린다", "모르겠다"):
            k = r["현재가_출처"] or "읽기 실패"; out["p0_출처"][k] = out["p0_출처"].get(k, 0) + 1
    for h in horizons:
        name, thr = h["이름"], h["기준폭"]
        rows = [p for p in prices if p["시간"] == name and p["기록ID"] in mine and mine[p["기록ID"]]["내판단"] != "취소"]
        stat = {"읽음": 0, "놓침": 0, "읽기실패": 0, "p0 없음": 0}
        src = {}
        items = []   # (기록ID, 실제, 변화)
        for p in rows:
            if p["상태"] != "읽음": stat[p["상태"]] = stat.get(p["상태"], 0) + 1; continue
            if p["변화"] == "": stat["p0 없음"] += 1; continue
            stat["읽음"] += 1; src[p["출처"] or "?"] = src.get(p["출처"] or "?", 0) + 1
            chg = float(p["변화"]); items.append((p["기록ID"], direction_of(chg, thr), chg))
        actual = {rid: a for rid, a, _ in items}
        my_calls = [(MINE[mine[rid]["내판단"]], a) for rid, a, _ in items if mine[rid]["내판단"] in MINE]
        dunno = [a for rid, a, _ in items if mine[rid]["내판단"] == "모르겠다"]
        ai_scores, agree_scores, disagree_mine = {}, {}, {}
        for kname, get in AI_KINDS:
            calls, agree, dis = [], [], []
            for rid, a, _ in items:
                d = get(ai.get(rid, {}))
                if d in HIT:
                    calls.append((d, a))
                    m = MINE.get(mine[rid]["내판단"])
                    if m == d: agree.append((d, a))
                    elif m: dis.append((m, a))
            ai_scores[kname], agree_scores[kname], disagree_mine[kname] = score(calls), score(agree), score(dis)
        n_all = len(items)
        base_up = score([("상승", a) for _, a, _ in items]); base_dn = score([("하락", a) for _, a, _ in items])
        sweep = []
        for mult in (0, 0.5, 1, 2):
            t = thr * mult
            act = {rid: direction_of(c, t) for rid, _, c in items}
            sweep.append(dict(기준폭=t, 내판단=score([(MINE[mine[rid]["내판단"]], act[rid]) for rid, _, _ in items if mine[rid]["내판단"] in MINE]),
                              큰봉알림=score([(AI_KINDS[1][1](ai.get(rid, {})), act[rid]) for rid, _, _ in items
                                             if AI_KINDS[1][1](ai.get(rid, {})) in HIT])))
        # 큰 봉 분봉별 (선택 창에서 고른 분봉. 예전 기록은 '미입력')
        tf_of = lambda rid: mine[rid].get("큰봉분봉") or "미입력"
        by_tf = {}
        for tf in sorted({tf_of(rid) for rid, _, _ in items}, key=tf_sort):
            sub = [(rid, a) for rid, a, _ in items if tf_of(rid) == tf]
            def ai_score(get):
                return score([(get(ai.get(rid, {})), a) for rid, a in sub if get(ai.get(rid, {})) in HIT])
            by_tf[tf] = dict(채점수=len(sub),
                             내판단=score([(MINE[mine[rid]["내판단"]], a) for rid, a in sub if mine[rid]["내판단"] in MINE]),
                             큰봉알림=ai_score(AI_KINDS[1][1]), 큰봉3분류=ai_score(AI_KINDS[0][1]), 진입확인=ai_score(AI_KINDS[4][1]),
                             늘오른다=score([("상승", a) for _, a in sub]))
        out["시간별"][name] = dict(기준폭=thr, 상태=stat, 출처=src, 채점수=n_all, 분봉별=by_tf,
                                 실제분포={k: sum(a == k for a in actual.values()) for k in ("올랐음", "내렸음", "변동 작음")},
                                 내판단=score(my_calls), 모르겠다일때={k: dunno.count(k) for k in ("올랐음", "내렸음", "변동 작음")},
                                 AI=ai_scores, 같을때=agree_scores, 다를때_내판단=disagree_mine,
                                 늘오른다=base_up, 늘내린다=base_dn, 기준폭바꿔보기=sweep)
    return out

def report(out, base, horizons, when):
    L = [f"# 실전 기록 결과 ({when:%Y-%m-%d %H:%M})", "",
         f"- 기록: 오른다 {out['기록수']['오른다']}, 내린다 {out['기록수']['내린다']}, 모르겠다 {out['기록수']['모르겠다']}"
         f" (취소 {out['기록수']['취소']}) — {out['기록한_날수']}일에 걸쳐",
         f"- 기록 때 현재가(p0) 출처: {out['p0_출처']}",
         "- 실제 방향: 변화 ≥ 기준 폭 → 올랐음, ≤ −기준 폭 → 내렸음, 그 사이 → 변동 작음. 적중률에서 변동 작음은 틀린 것으로 셈",
         "- 같은 날 가까운 시각의 기록은 결과가 겹쳐(같은 가격 흐름) 서로 독립이 아니다. 건수가 적으면 몇 건 차이로 %가 크게 움직인다.",
         "- 같은 시간(예: 30분 뒤)이라도 큰 봉 분봉에 따라 봉 몇 개 뒤인지가 다르다 (1분봉이면 30봉 뒤, 300분봉이면 봉 1개도 안 지남).",
         "- 주문은 사람이 한다. 이 표는 투자 조언이 아니다.", ""]
    for h in horizons:
        r = out["시간별"][h["이름"]]
        st = r["상태"]
        L += [f"## {h['이름']} 뒤 (기준 폭 {r['기준폭']:g}포인트)", "",
              f"- 채점한 기록 {r['채점수']}건 (놓침 {st.get('놓침', 0)}, 읽기실패 {st.get('읽기실패', 0)}, p0 없음 {st.get('p0 없음', 0)}) · "
              f"현재가 출처 {r['출처']}",
              f"- 실제: 올랐음 {r['실제분포']['올랐음']}, 내렸음 {r['실제분포']['내렸음']}, 변동 작음 {r['실제분포']['변동 작음']}", "",
              "### 목표 판정 (problem_definition.md 5장 ⑪⑫⑬)", "",
              "| 번호 | 무엇을 | 값 | 기준 | 결과 | 참고 |", "| --- | --- | --- | --- | --- | --- |"]
        r["목표판정"] = judge_targets(r)
        L += [f"| {t['번호']} | {t['대상']} | {t['값']} | {t['기준']} | **{t['결과']}** | {t['설명']} |" for t in r["목표판정"]]
        L += ["", "- 기록이 30건 정도면 우연으로도 적중률이 ±10%p쯤 흔들린다(95% 범위로는 약 ±18%p). 차이가 10%p 안팎이면 확실하다고 보지 않는다.", "",
              "### 적중률", "",
              "| 누구 | 적중률 (맞음/방향을 말한 수) · 반대 · 변동 작음 · 변동 작음 뺀 적중률 |", "| --- | --- |",
              f"| **내 판단** | {fmt(r['내판단'])} |"]
        L += [f"| AI: {k} | {fmt(v)} |" for k, v in r["AI"].items()]
        L += [f"| 늘 오른다 (비교 기준) | {fmt(r['늘오른다'])} |", f"| 늘 내린다 (비교 기준) | {fmt(r['늘내린다'])} |", "",
              f"- 내가 \"모르겠다\"였을 때 실제: {r['모르겠다일때']}", "",
              "| 나와 AI가 **같은** 방향일 때 | 적중률 | 나와 AI가 **다를** 때 내 판단 |", "| --- | --- | --- |"]
        L += [f"| {k} | {fmt(r['같을때'][k])} | {fmt(r['다를때_내판단'][k])} |" for k in r["같을때"]]
        L += ["", "큰 봉 분봉별 (선택 창에서 고른 분봉 — 300분봉으로 학습한 AI가 다른 분봉에서도 통하는지):", "",
              "| 큰 봉 분봉 | 채점 수 | 내 판단 | AI 큰 봉 알림 | AI 큰 봉 3분류 | AI 진입 확인 | 늘 오른다 |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
        sh = lambda s: f"{pct(s['적중률'])} ({s['맞음']}/{s['수']})"
        L += [f"| {tf} | {v['채점수']} | {sh(v['내판단'])} | {sh(v['큰봉알림'])} | {sh(v['큰봉3분류'])} | {sh(v['진입확인'])} | {sh(v['늘오른다'])} |"
              for tf, v in r["분봉별"].items()]
        L += ["", "기준 폭을 바꿔 보면:", "", "| 기준 폭 | 내 판단 | AI 큰 봉 알림 |", "| --- | --- | --- |"]
        L += [f"| {s['기준폭']:g} | {pct(s['내판단']['적중률'])} ({s['내판단']['맞음']}/{s['내판단']['수']}) | "
              f"{pct(s['큰봉알림']['적중률'])} ({s['큰봉알림']['맞음']}/{s['큰봉알림']['수']}) |" for s in r["기준폭바꿔보기"]]
        L.append("")
    return L

def main():
    ap = argparse.ArgumentParser(description="실전 기록 결과 표 (내 판단 vs AI vs 실제 가격 변화)")
    ap.add_argument("--log-dir", type=Path, default=C.ROOT / "logs")
    ap.add_argument("--thr", help="기준 폭 바꾸기. 예: 30분=25,2시간=50,1일=80")
    ap.add_argument("--out", type=Path, default=C.ROOT / "진행기록" / "시험결과")
    args = ap.parse_args()
    base = args.log_dir / "실전기록"
    if not (base / "내판단.csv").exists():
        sys.exit(f"기록이 없습니다: {base / '내판단.csv'}  (record_live.py로 기록을 먼저 모으세요)")
    cfg = C.load_config()
    horizons = [dict(h) for h in cfg.get("horizons", DEFAULT_HORIZONS)]
    if args.thr:
        over = dict(part.split("=") for part in args.thr.split(","))
        for h in horizons:
            if h["이름"] in over: h["기준폭"] = float(over[h["이름"]])
    when = datetime.now()
    out = evaluate(base, horizons)
    L = report(out, base, horizons, when)
    args.out.mkdir(parents=True, exist_ok=True)
    md = args.out / f"실전기록_{C.stamp(when)}.md"
    md.write_text("\n".join(L) + "\n", encoding="utf-8")
    (args.out / f"실전기록_{C.stamp(when)}.json").write_text(json.dumps(dict(시각=when.isoformat(timespec="seconds"),
        기준=horizons, **out), ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(L)); print("저장:", md)

if __name__ == "__main__":
    main()
