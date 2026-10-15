"""exe のアイコン (assets/icon.ico) を作る。

    .venv\\Scripts\\python tools\\make_icon.py

ストップウォッチに「残り時間」の扇形を重ねた絵。4 倍の大きさで描いてから縮めて
輪郭のギザギザを消し、16〜256px の全サイズを 1 つの .ico に入れる。
"""

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "icon.ico")

BG = (18, 20, 23, 255)
RING = (242, 242, 242, 255)
WARN = (255, 210, 63, 255)
DANGER = (255, 77, 77, 255)

SS = 4                       # 描画時の拡大率
SIZE = 256 * SS


def draw():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def s(v):
        return int(v * SS)

    d.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=s(48), fill=BG)

    # 竜頭 (上のボタン)
    d.rounded_rectangle([s(110), s(22), s(146), s(52)], radius=s(6), fill=RING)

    cx, cy, r = s(128), s(146), s(88)
    box = [cx - r, cy - r, cx + r, cy + r]
    d.ellipse(box, outline=RING, width=s(16))

    # 残り時間の扇形。12 時から時計回りに、黄色の後ろへ赤 (もうすぐ湧く) を少し
    inner = s(66)
    ibox = [cx - inner, cy - inner, cx + inner, cy + inner]
    d.pieslice(ibox, start=-90, end=170, fill=WARN)
    d.pieslice(ibox, start=170, end=230, fill=DANGER)
    return img.resize((256, 256), Image.LANCZOS)


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    draw().save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                            (128, 128), (256, 256)])
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
