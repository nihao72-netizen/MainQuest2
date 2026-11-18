"""
5단계: 학습 때와 실제 판정 때 전처리가 같은지 확인하는 테스트

실행:  python code/poc/test_preprocess.py          (모두 통과하면 "전부 통과", 하나라도 틀리면 종료 코드 1)

테스트
1. 같은 원본캡처를 두 경로로 처리 → 모델 입력 사진이 픽셀까지 같고, 두 모델의 점수도 같은가
   - 학습 경로: 원본캡처에서 그 구간을 잘라 PNG 파일로 저장했다가 다시 읽기 → preprocess.prepare (train_final.py와 같음)
   - 판정 경로: 좌표 도우미로 찾은 차트 영역 → judge.cut_windows (run_poc.py와 같음)
2. 학습 코드(train_final.py)와 판정 코드(judge.py)가 정말 preprocess.prepare를 부르는가
3. 직접 캡처 학습 사진에서, PoC 전처리 = 교차검증(진행기록 07–11) 전처리인가
4. 뒤집기를 두 번 하면 원래 사진으로 돌아오는가
5. 알림 규칙: 3분류 점수 최소값(min_dir3_score)이 기대대로 동작하는가
6. 진입 확인 규칙: 큰 봉 알림 방향 = 작은 봉 알림 방향일 때만 진입 확인인가
"""
import inspect, sys, tempfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import preprocess as P
import capture as C
import judge as J
import rules as R
import setup_region as S
import train_final as T

ROOT = C.ROOT
_results = []

def check(name, ok, detail=""):
    _results.append(ok)
    print(f"[{'통과' if ok else '실패'}] {name}" + (f" — {detail}" if detail else ""))

def test_two_paths_same(judge=None, files=None, bars=(100, 150, 200)):
    files = files or sorted((ROOT / "data" / "원본캡처").glob("*.png"))[:3]
    for f in files:
        full = P.Image.open(f).convert("RGB")
        ar = S.find_plot_areas(full)[0]
        region = full.crop((ar["left"], ar["top"], ar["right"], ar["bottom"]))      # = grab_region 결과
        layout = J.bar_layout(region)
        for w in J.cut_windows(region, list(bars), 9, layout):
            # 학습 경로: 원본에서 같은 구간을 잘라 파일로 저장 → 다시 읽기 → prepare
            box = (ar["left"] + w["x0"], ar["top"], ar["left"] + w["x1"], ar["bottom"])
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / "train_like.png"; full.crop(box).save(p)
                a = P.prepare(P.Image.open(p))
            same = np.array_equal(np.asarray(a), np.asarray(w["img"]))
            detail = f"{f.stem} {w['bars']}봉 창"
            if same and judge is not None:
                ra, rb = judge(a), judge(w["img"])
                same = ra["dir3_점수"] == rb["dir3_점수"] and ra["cls11_점수"] == rb["cls11_점수"]
                detail += ", 두 모델 점수도 같음" if same else ", 모델 점수가 다름!"
            check("같은 원본을 학습 경로·판정 경로로 처리한 결과가 같다", same, detail)

def test_same_function_called():
    src_train = inspect.getsource(T.build_dataset)
    src_judge = inspect.getsource(J.cut_windows)
    check("학습 코드(train_final.build_dataset)가 preprocess.prepare를 쓴다", "P.prepare(" in src_train)
    check("판정 코드(judge.cut_windows)가 preprocess.prepare를 쓴다", "P.prepare(" in src_judge)

def test_matches_cross_validation():
    sys.path.insert(0, str(ROOT / "code" / "yolo_direction"))
    import run_yolo_direction as CV
    man = [f for f in sorted((ROOT / "data" / "학습용").glob("*/*.png")) if "원본" not in f.name]
    same = sum(np.array_equal(np.asarray(P.prepare(P.Image.open(f))),
                              np.asarray(CV.to32(CV.clean(P.Image.open(f).convert("RGB"))))) for f in man)
    check("직접 캡처 학습 사진: PoC 전처리 = 교차검증 전처리", same == len(man), f"{same}/{len(man)}장 같음")
    auto = [f for f in sorted((ROOT / "data" / "학습용").glob("*/*.png")) if "원본" in f.name]
    d = [np.abs(np.asarray(P.prepare(P.Image.open(f)), float) - np.asarray(CV.to32(P.Image.open(f).convert("RGB")), float)).mean()
         for f in auto]
    print(f"   (참고) 자동 자른 사진 {len(auto)}장: 교차검증은 정리 없이 크기만 맞췄고, PoC는 정리를 한 번 더 함 → "
          f"픽셀 평균 차이 {np.mean(d):.2f} (0–255). 최종 모델은 PoC 방식으로 학습했으므로 판정과는 일치")

def test_flip_twice():
    f = sorted((ROOT / "data" / "학습용").glob("*/*.png"))[0]
    im = P.prepare(P.Image.open(f))
    check("뒤집기를 두 번 하면 원래 사진", np.array_equal(np.asarray(P.flip(P.flip(im))), np.asarray(im)))

def test_min_score_rule():
    cases = [  # (dir3, cls11방향, 점수, 기준, 기대)
        ("상승", "상승", 0.52, 0.0, (R.ALERT, "상승")),
        ("상승", "상승", 0.52, 0.6, (R.UNSURE, None)),
        ("상승", "상승", 0.95, 0.6, (R.ALERT, "상승")),
        ("하락", "상승", 0.95, 0.0, (R.UNSURE, None)),
        ("없음", "없음", 0.30, 0.6, (R.NONE, "없음")),
    ]
    ok = all(R.decide(a, b, "agree", s, t) == e for a, b, s, t, e in cases)
    check("3분류 점수 최소값 규칙 (기본 0이면 이전과 같음, 낮은 점수의 알림은 애매로)", ok)

def test_entry_rule():
    A, U, N = R.ALERT, R.UNSURE, R.NONE
    cases = [((A, "상승"), (A, "상승"), True), ((A, "하락"), (A, "상승"), False), ((A, "하락"), (U, None), False),
             ((U, None), (A, "하락"), False), ((N, "없음"), (N, "없음"), False), ((A, "상승"), None, False)]
    ok = all(R.entry_check(b, s)[0] == e for b, s, e in cases)
    check("진입 확인 규칙 (큰 봉 알림 방향 = 작은 봉 알림 방향일 때만)", ok)

def main():
    print("전처리·규칙 테스트\n")
    try:
        judge = J.Judge(J.settings(C.load_config())["models_dir"])
    except Exception as e:
        judge = None; print(f"(모델을 불러오지 못해 점수 비교는 건너뜀: {e})")
    test_two_paths_same(judge)
    test_same_function_called()
    test_matches_cross_validation()
    test_flip_twice()
    test_min_score_rule()
    test_entry_rule()
    n_fail = _results.count(False)
    print(f"\n{'전부 통과' if not n_fail else f'{n_fail}개 실패'} ({len(_results)}개 중)")
    sys.exit(1 if n_fail else 0)

if __name__ == "__main__":
    main()
