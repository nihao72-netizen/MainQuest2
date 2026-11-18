"""
PoC 3단계: 알림 규칙 (바꾸기 쉽게 이 파일에만 둔다)

- 창 하나의 규칙: config의 "rule" 이름으로 고른다. 기본 "agree" = 진행기록 10번에서 확인한 "두 모델이 같을 때만 알림"
- 여러 창을 묶는 규칙: config의 "window_combine" 이름으로 고른다.

판정 글자는 세 가지다: "알림", "애매(쉬어 가기)", "없음"
화면이 차트가 아니면(다른 창에 가려짐 등) 판정하지 않고 "확인 불가"를 남긴다.
"""
ALERT, UNSURE, NONE = "알림", "애매(쉬어 가기)", "없음"
NOT_CHART = "확인 불가"

# ---------- 창 하나: 두 모델의 방향 → 판정 ----------
RULES = {}
def _rule(name):
    def reg(f): RULES[name] = f; return f
    return reg

@_rule("agree")
def agree(dir3, cls11_dir):
    """3분류 방향과 11분류(방향으로 바꾼 것)가 같고 '없음'이 아니면 알림, 다르면 애매, 둘 다 없음이면 없음"""
    if dir3 != cls11_dir:
        return UNSURE, None
    return (NONE, "없음") if dir3 == "없음" else (ALERT, dir3)

@_rule("dir3_only")
def dir3_only(dir3, cls11_dir):
    """비교용: 3분류만 보고 판정 (11분류는 참고만)"""
    return (NONE, "없음") if dir3 == "없음" else (ALERT, dir3)

def decide(dir3, cls11_dir, rule="agree", dir3_score=None, min_dir3_score=0.0):
    """min_dir3_score: 3분류 점수(1위 클래스)가 이보다 낮으면, 규칙이 '알림'이라고 해도 '애매(쉬어 가기)'로 바꾼다.
    기본 0 = 점수를 보지 않음 (이전과 같음). 기준값은 시험 결과를 보고 정한다."""
    if rule not in RULES:
        raise ValueError(f"알 수 없는 규칙 '{rule}'. 가능한 값: {list(RULES)}")
    judge, d = RULES[rule](dir3, cls11_dir)
    if judge == ALERT and dir3_score is not None and dir3_score < min_dir3_score:
        return UNSURE, None
    return judge, d

# ---------- 여러 창: 창별 판정 → 최종 판정 ----------
def combine(windows, how="main", main_bars=150):
    """windows: [{'bars': 100, '판정': ..., '방향': ...}, ...] → (최종 판정, 방향, 설명)"""
    if not windows:
        return NONE, "없음", "판정할 창 없음"
    if how == "main":
        w = min(windows, key=lambda w: abs(w["bars"] - main_bars))
        return w["판정"], w["방향"], f"{w['bars']}봉 창 기준"
    if how == "all_agree":
        if all(w["판정"] == ALERT for w in windows) and len({w["방향"] for w in windows}) == 1:
            return ALERT, windows[0]["방향"], "모든 창이 같은 방향"
        if all(w["판정"] == NONE for w in windows):
            return NONE, "없음", "모든 창이 없음"
        return UNSURE, None, "창마다 다름"
    if how == "majority":
        need = len(windows) // 2 + 1                     # 창 3개면 2개 이상
        for d in ("상승", "하락"):
            k = sum(w["판정"] == ALERT and w["방향"] == d for w in windows)
            if k >= need: return ALERT, d, f"{len(windows)}개 창 중 {k}개가 {d}"
        k = sum(w["판정"] == NONE for w in windows)
        if k >= need: return NONE, "없음", f"{len(windows)}개 창 중 {k}개가 없음"
        return UNSURE, None, "과반 없음"
    raise ValueError(f"알 수 없는 window_combine '{how}'. 가능한 값: {COMBINES}")

COMBINES = ["main", "all_agree", "majority"]

# ---------- 두 차트: 큰 봉 + 작은 봉 → 진입 확인 ----------
ENTRY = "진입 확인"

def entry_check(big, small):
    """big, small: 각 차트의 (최종 판정, 방향). 없거나 '확인 불가'면 None.
    큰 봉이 '알림'이고 작은 봉도 '알림'이며 방향이 같을 때만 진입 확인 → (True, 방향, 설명). 주문은 사람이 한다."""
    def txt(name, x):
        if x is None: return f"{name} 판정 없음"
        return f"{name} {x[0]}" + (f"({x[1]})" if x[0] == ALERT else "")
    desc = f"{txt('큰 봉', big)}, {txt('작은 봉', small)}"
    if big and small and big[0] == ALERT and small[0] == ALERT and big[1] == small[1]:
        return True, big[1], f"큰 봉 알림({big[1]}) = 작은 봉 알림({small[1]})"
    return False, None, desc
