#!/usr/bin/env python3
"""
数学风格封面生成器
流程：DashScope Wanx 生成背景图 → Pillow 叠加中文标题
用法：
    export DASHSCOPE_API_KEY="sk-..."
    python scripts/make_math_cover_qwen.py
"""
import io
import os
import time
import sys
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

# ── 配置 ────────────────────────────────────────────────────────────────────
API_KEY   = os.environ.get("DASHSCOPE_API_KEY", "")
OUT_PATH  = Path("assets/math_cover_qwen.png")
W, H      = 1080, 1080

LINE1 = "数学界被这发现炸了"
LINE2 = "1个函数统治所有运算！"

# Wanx 图像生成 prompt（英文效果更稳定）
IMAGE_PROMPT = (
    "Dark deep-blue chalkboard background with glowing mathematical formulas "
    "scattered in space: sin(x), cos(x), e^x, ln(x), integral signs, summation "
    "symbols, golden circle in center radiating arrows to surrounding equations, "
    "faint coordinate grid lines, chalk-white handwritten style formulas, "
    "mystical mathematics universe, clean minimalist, cinematic lighting, "
    "no text, no letters, pure visual art"
)
NEGATIVE_PROMPT = "text, letters, words, watermark, ugly, blurry, low quality"

# ── 颜色 ────────────────────────────────────────────────────────────────────
WHITE      = (255, 255, 255)
YELLOW     = (255, 210, 40)
SHADOW     = (0, 0, 0)
RED_LINE   = (220, 60, 60)
FOOTER_CLR = (200, 210, 220)


# ══════════════════════════════════════════════════════════════════════════════
# 1. DashScope Wanx 图像生成（HTTP，无需 SDK）
# ══════════════════════════════════════════════════════════════════════════════

def wanx_generate(prompt: str, negative: str) -> str:
    """提交生成任务，返回图片 URL。"""
    if not API_KEY:
        print("❌ 请先设置 DASHSCOPE_API_KEY")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type":  "application/json",
        "X-DashScope-Async": "enable",
    }
    body = {
        "model": "wanx2.1-t2i-turbo",
        "input": {
            "prompt":          prompt,
            "negative_prompt": negative,
        },
        "parameters": {
            "size":    "1024*1024",
            "n":       1,
            "style":   "<auto>",
        },
    }

    print("🎨 提交 Wanx 生成任务…")
    resp = requests.post(
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis",
        headers=headers,
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    data    = resp.json()
    task_id = data["output"]["task_id"]
    print(f"   task_id: {task_id}")

    # ── 轮询结果 ──
    poll_url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
    poll_headers = {"Authorization": f"Bearer {API_KEY}"}

    for attempt in range(60):
        time.sleep(3)
        poll = requests.get(poll_url, headers=poll_headers, timeout=15).json()
        status = poll["output"]["task_status"]
        print(f"   [{attempt+1:02d}] status: {status}")

        if status == "SUCCEEDED":
            url = poll["output"]["results"][0]["url"]
            print(f"   ✅ 图片 URL: {url[:80]}…")
            return url

        if status in ("FAILED", "CANCELED"):
            print(f"❌ 生成失败：{poll}")
            sys.exit(1)

    print("❌ 超时（60 次轮询）")
    sys.exit(1)


def download_image(url: str) -> Image.Image:
    print("⬇️  下载图片…")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    img = img.resize((W, H), Image.LANCZOS)
    print(f"   ✅ 图片尺寸：{img.size}")
    return img


# ══════════════════════════════════════════════════════════════════════════════
# 2. Pillow 叠加标题
# ══════════════════════════════════════════════════════════════════════════════

def find_font() -> str | None:
    for p in [
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Songti.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]:
        if Path(p).exists():
            return p
    return None


def overlay_title(img: Image.Image) -> Image.Image:
    draw = ImageDraw.Draw(img)
    fp   = find_font()

    def font(size: int):
        if fp:
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
        return ImageFont.load_default(size=size)

    def center_x(text: str, f) -> int:
        bb = draw.textbbox((0, 0), text, font=f)
        return (W - (bb[2] - bb[0])) // 2

    def draw_with_shadow(text, x, y, f, fill, shadow_offset=4):
        draw.text((x + shadow_offset, y + shadow_offset), text, font=f, fill=SHADOW)
        draw.text((x, y), text, font=f, fill=fill)

    # ── 顶部半透明暗条（标题区域对比度）──
    overlay = Image.new("RGBA", (W, 260), (0, 0, 0, 160))
    img.paste(Image.new("RGB", (W, 260), (0, 0, 0)),
              (0, 40), overlay.split()[3])

    # ── 第一行：白色大字 ──
    f1 = font(96)
    x1 = center_x(LINE1, f1)
    draw_with_shadow(LINE1, x1, 58, f1, WHITE)

    # ── 第二行：金黄色 ──
    f2 = font(74)
    x2 = center_x(LINE2, f2)
    draw_with_shadow(LINE2, x2, 170, f2, YELLOW)

    # ── 标题下红色强调线 ──
    draw.line([(W // 2 - 230, 262), (W // 2 + 230, 262)], fill=RED_LINE, width=3)

    # ── 底部品牌条 ──
    bar = Image.new("RGBA", (W, 70), (0, 0, 0, 180))
    img.paste(Image.new("RGB", (W, 70), (0, 0, 0)),
              (0, H - 70), bar.split()[3])

    footer = "AI 日报  ·  #数学  #数学之美  #万能函数"
    f_foot = font(28)
    bb     = draw.textbbox((0, 0), footer, font=f_foot)
    draw.text(((W - (bb[2] - bb[0])) // 2, H - 54), footer, font=f_foot, fill=FOOTER_CLR)

    return img


# ══════════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    img_url = wanx_generate(IMAGE_PROMPT, NEGATIVE_PROMPT)
    img     = download_image(img_url)
    img     = overlay_title(img)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(OUT_PATH), "PNG")
    print(f"\n✅ 封面已保存：{OUT_PATH}")


if __name__ == "__main__":
    main()
