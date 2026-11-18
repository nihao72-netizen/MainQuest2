"""
PoC 2단계: 화면 캡처와 저장 (모두 내 PC 안에서만 동작, 외부 전송 없음)

- grab_region(): 정기 캡처용. config의 차트 영역만 찍는다 (화면 전체는 찍지 않음 → 계좌·주문 정보가 담기지 않음)
- grab_full():   좌표 도우미 전용. 화면 전체를 메모리로만 가져온다 (파일 저장은 호출하는 쪽이 설정을 보고 결정)
- save_keep():   날짜·시각 이름으로 저장 (덮어쓰지 않음), 보관 개수를 넘으면 오래된 것부터 지움
"""
import json
from datetime import datetime
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]          # MainQuest2 폴더
CONFIG = Path(__file__).resolve().parent / "config.json"

BIG, SMALL = "큰 봉", "작은 봉"        # 화면 위 차트 = 큰 봉, 아래 차트 = 작은 봉 (분봉 이름은 쓰지 않음 — 사용자가 수시로 바꿈)
CHART_NAMES = [BIG, SMALL]
CHART_FILE = {BIG: "큰봉", SMALL: "작은봉"}   # 파일 이름용 (띄어쓰기 없이)

def _default_charts():
    return {BIG: {"위치": "위", "region": None, "bar_px": None},
            SMALL: {"위치": "아래", "region": None, "bar_px": None}}

DEFAULT_CONFIG = {
    "_설명": "PoC 설정. 값은 코드가 아니라 이 파일에서 바꾼다. 좌표는 setup_region.py가 채운다. "
             "charts: 화면 위 차트 = 큰 봉, 아래 차트 = 작은 봉. bar_px = 그 차트에서 봉 하나가 차지하는 가로 픽셀(null이면 공통 bar_px).",
    "monitor": 1,
    "charts": None,
    "save_full_screenshot": False,
    "keep_captures": 2000,
}

def chart_name(s):
    """'작은봉', 'small', '아래' 등을 '작은 봉'으로"""
    t = str(s).replace(" ", "").lower()
    if t in ("큰봉", "big", "위", "top"): return BIG
    if t in ("작은봉", "small", "아래", "bottom"): return SMALL
    raise ValueError(f"차트 이름은 '큰 봉' 또는 '작은 봉': {s}")

def load_config(path=CONFIG):
    cfg = dict(DEFAULT_CONFIG)
    if Path(path).exists():
        cfg.update(json.loads(Path(path).read_text(encoding="utf-8")))
    charts = _default_charts()
    old = cfg.get("charts") or {}
    for key, c in old.items():                       # 예전 이름(위/아래)도 새 이름으로 옮김, 분봉 이름 칸은 버림
        try: name = chart_name(key)
        except ValueError: continue
        for k in ("region", "bar_px"):
            if c.get(k) is not None: charts[name][k] = c[k]
    if cfg.get("region") and not charts[BIG]["region"]:   # 더 예전 형식(region 하나)
        charts[BIG]["region"] = cfg["region"]
    cfg.pop("region", None)
    cfg["charts"] = charts
    cfg["_설명"] = DEFAULT_CONFIG["_설명"]
    return cfg

def chart_region(cfg, name=BIG):
    return cfg["charts"][name].get("region")

def save_config(cfg, path=CONFIG):
    Path(path).write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")

def _to_pil(shot):
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

def grab_full(monitor=1):
    """화면 전체 (좌표 도우미 전용). 돌려주는 값: (사진, 모니터 왼쪽 위 좌표)"""
    import mss
    with mss.mss() as sct:
        mon = sct.monitors[monitor]
        return _to_pil(sct.grab(mon)), (mon["left"], mon["top"])

def grab_region(region):
    """config의 차트 영역만 캡처. region = {left, top, width, height} (화면 절대 좌표)"""
    import mss
    if not region:
        raise ValueError("config.json에 region이 없습니다. 먼저 setup_region.py를 실행하세요.")
    box = {k: int(region[k]) for k in ("left", "top", "width", "height")}
    with mss.mss() as sct:
        return _to_pil(sct.grab(box))

def stamp(now=None):
    return (now or datetime.now()).strftime("%Y%m%d_%H%M%S")

def save_keep(img, folder, name, keep=0):
    """folder/name.png 로 저장. 같은 이름이 있으면 _1, _2 …를 붙여 덮어쓰지 않음.
    keep > 0 이면 folder 안의 png가 keep개를 넘을 때 오래된 것부터 지움 (0 이하 = 지우지 않음)"""
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{name}.png"; k = 1
    while p.exists():
        p = folder / f"{name}_{k}.png"; k += 1
    img.save(p)
    if keep and keep > 0:
        files = sorted(folder.glob("*.png"), key=lambda f: f.stat().st_mtime)
        for old in files[:-keep]:
            old.unlink()
    return p
