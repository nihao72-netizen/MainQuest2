import numpy as np
from PIL import Image
CLASSES=["쌍바닥","삼중바닥","역헤드앤숄더","N자형","상승추세","쌍봉","삼중천장","헤드앤숄더","역N자형","하락추세","횡보"]
MIRROR={"쌍바닥":"쌍봉","삼중바닥":"삼중천장","역헤드앤숄더":"헤드앤숄더","N자형":"역N자형","상승추세":"하락추세","횡보":"횡보"}
MIRROR.update({v:k for k,v in list(MIRROR.items())})
UP={"쌍바닥","삼중바닥","역헤드앤숄더","N자형","상승추세"}; DOWN={MIRROR[c] for c in UP}
def direction(c): return "상승" if c in UP else ("하락" if c in DOWN else "없음")
def flip(im):
    a=np.array(im.convert("RGB"))[::-1].copy(); a=a[...,[2,1,0]]  # swap red<->blue roughly
    return Image.fromarray(a)
