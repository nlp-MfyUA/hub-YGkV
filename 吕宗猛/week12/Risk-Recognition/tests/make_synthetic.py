# -*- coding: utf-8 -*-
"""
生成「楼道 + 电动车」合成验证图（用于验证高风险档可被触发）。

做法：把真实电动车照片以羽化蒙版贴进真实楼道照片的门厅地面区域。
用途：仅作功能验证素材（高风险档），非演示素材、不对外发布。

输入：
    tests/samples/corridor_door_clutter.jpg            真实楼道底图
    tests/samples/source_ebike_scooters_ccbysa4.jpg    真实电动车素材（CC BY-SA 4.0）
输出：
    tests/samples/synthetic_corridor_ebike.jpg

用法：python tests/make_synthetic.py
"""
import os
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "tests" / "samples"
OUT = SAMPLES / "synthetic_corridor_ebike.jpg"

BASE_IMG = SAMPLES / "corridor_door_clutter.jpg"
BIKE_IMG = SAMPLES / "source_ebike_scooters_ccbysa4.jpg"

# 电动车素材中停放踏板车的区域（左下角，含台阶背景）
BIKE_CROP = (0, 560, 620, 853)
# 贴入位置（相对底图宽高）
PASTE_X = 140
PASTE_Y_RATIO = 0.56
PATCH_W = 500
BRIGHTNESS = 1.75
# 贴图亮度系数：1.0 = 保持原图亮度。
# 实测：压暗到 0.42 会让模型把踏板车当成「贴图上的物件」而只判中风险；
# 保持原亮度时模型能识别出电动车并触发高风险规则（实测 7/8 次判高风险）。
PATCH_DARKEN = 1.0


def feather_mask(w, h):
    """中部实心、四周羽化的蒙版，让贴图与底图自然衔接。"""
    mask = Image.new("L", (w, h), 0)
    px = mask.load()
    for y in range(h):
        for x in range(w):
            dx = min(x, w - 1 - x) / (w * 0.18)
            dy = min(y, h - 1 - y) / (h * 0.18)
            v = max(0.0, min(1.0, min(dx, dy)))
            px[x, y] = int(255 * v)
    return mask.filter(ImageFilter.GaussianBlur(6))


def main():
    if not BASE_IMG.exists() or not BIKE_IMG.exists():
        raise SystemExit("缺少输入样本图")
    corridor = Image.open(BASE_IMG).convert("RGB")
    bike_src = Image.open(BIKE_IMG).convert("RGB")
    bike = bike_src.crop(BIKE_CROP)

    canvas = ImageEnhance.Brightness(corridor).enhance(BRIGHTNESS)
    tw = PATCH_W
    th = int(bike.height * tw / bike.width)
    patch = bike.resize((tw, th)).filter(ImageFilter.GaussianBlur(0.5))
    patch = ImageEnhance.Brightness(patch).enhance(PATCH_DARKEN)
    mask = feather_mask(tw, th)

    px, py = PASTE_X, int(canvas.height * PASTE_Y_RATIO)
    canvas.paste(patch, (px, py), mask)
    canvas.save(OUT, "JPEG", quality=92)
    print("saved:", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
