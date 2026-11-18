"""
5단계 공통 채점 함수 (모델 시험·PoC 실전 시험이 같이 씀)

판정(알림/애매/없음)과 정답 방향(상승/하락/없음)을 비교하는 기준:
- 알림 정확도  = 알림 중 방향이 맞은 비율            ("알림이 오면 믿을 만한가")
- 알림 적중    = 방향이 있는 사진 중 맞게 알린 비율   ("방향이 있을 때 놓치지 않는가")
- 위험한 알림  = 정답이 '없음'인데 상승·하락을 알린 수 (애매한 자리에 진입하게 만드는 가장 위험한 실수)
- 반대 알림    = 정답과 반대 방향으로 알린 수
"""
import csv
from pathlib import Path
import rules as R

THRESHOLDS = [round(0.1 * i, 1) for i in range(10)]          # 0.0, 0.1, ..., 0.9

def summarize(truth_dirs, decisions):
    """truth_dirs: ['상승', ...], decisions: [(판정, 방향), ...]"""
    n = len(truth_dirs)
    alerts = [(t, d) for t, (j, d) in zip(truth_dirs, decisions) if j == R.ALERT]
    hit = sum(t == d for t, d in alerts)
    directional = sum(t != "없음" for t in truth_dirs)
    return dict(
        사진수=n, 알림수=len(alerts), 알림_맞음=hit,
        알림정확도=(hit / len(alerts)) if alerts else None,
        알림적중=(hit / directional) if directional else None, 방향있는_사진=directional,
        위험한알림=sum(t == "없음" for t, d in alerts),
        반대알림=sum(t != "없음" and t != d for t, d in alerts),
        애매수=sum(j == R.UNSURE for j, _ in decisions),
        없음판정수=sum(j == R.NONE for j, _ in decisions),
        없음_맞음=sum(t == "없음" and j == R.NONE for t, (j, _) in zip(truth_dirs, decisions)),
        없음_사진=sum(t == "없음" for t in truth_dirs),
    )

def pct(x):
    return "—" if x is None else f"{x:.0%}"

def sweep_table(rows):
    """rows: [(기준값, summarize 결과)] → 마크다운 표"""
    out = ["| 3분류 점수 최소값 | 알림 수 | 알림 정확도 | 알림 적중 (방향 있는 사진 중) | 위험한 알림 | 반대 알림 | 애매 | 없음 판정 |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t, s in rows:
        out.append(f"| {t:.1f} | {s['알림수']} | {pct(s['알림정확도'])} ({s['알림_맞음']}/{s['알림수']}) | "
                   f"{pct(s['알림적중'])} ({s['알림_맞음']}/{s['방향있는_사진']}) | {s['위험한알림']} | {s['반대알림']} | "
                   f"{s['애매수']} | {s['없음판정수']} |")
    return "\n".join(out)

def acc(pairs):
    pairs = list(pairs)
    return (sum(a == b for a, b in pairs) / len(pairs)) if pairs else None

def read_label_suspects(path):
    """라벨 의심 목록 (파일 이름 → 메모). 점수는 원래 정답으로 매기고, 목록은 따로 보여 주기만 한다"""
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8-sig", newline="") as f:
        return {r["파일"].strip(): r.get("메모", "") for r in csv.DictReader(f) if r.get("파일", "").strip()}
