#!/usr/bin/env python3
"""
GitHub Trending AI 追踪器
每天 08:00 / 21:00（北京时间）抓取 GitHub Trending 当日 Top 10，
筛选 AI 相关项目，用 LLM 生成小红书风格 Issue，并可选发飞书通知。
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── 时区 & 常量 ─────────────────────────────────────────────────────────────
CST      = timezone(timedelta(hours=8))
NOW      = datetime.now(CST)
TODAY    = NOW.strftime("%Y-%m-%d")
TODAY_CN = NOW.strftime("%Y.%m.%d")
HOUR     = NOW.strftime("%H")          # "08" or "21"，用于 Issue 标题区分
SLOT     = "早报" if NOW.hour < 14 else "晚报"   # 08:00 → 早报，21:00 → 晚报

DATA_FILE = Path("trending_data.json")

AI_KEYWORDS = {
    "ai", "llm", "gpt", "claude", "gemini", "agent", "openai", "anthropic",
    "deepmind", "mistral", "llama", "stable-diffusion", "diffusion", "transformer",
    "rag", "fine-tun", "multimodal", "neural", "langchain", "hugging", "embedding",
    "vector", "inference", "vllm", "lora", "sora", "copilot", "midjourney",
    "image-generation", "text-to-image", "speech", "whisper", "tts", "vision",
    "chatbot", "deep-learning", "machine-learning", "generative", "foundation-model",
    "mcp", "model-context", "agentic",
}

# ── 环境变量 ─────────────────────────────────────────────────────────────────
LLM_API_KEY    = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL   = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_MODEL      = os.environ.get("LLM_MODEL", "gpt-4o-mini")
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO    = os.environ.get("GITHUB_REPOSITORY", "")
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")

ASSETS_DIR = Path("assets") / TODAY


# ══════════════════════════════════════════════════════════════════════════════
# 0. 封面图工具函数（Pillow · 白底黑字）
# ══════════════════════════════════════════════════════════════════════════════

def find_cjk_font(bold: bool = True) -> str | None:
    """查找可用的 CJK 字体路径"""
    candidates = [
        # Ubuntu/Debian (apt install fonts-noto-cjk)
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJKsc-Bold.otf",
        "/usr/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf",
        # WQY (apt install fonts-wqy-zenhei / fonts-wqy-microhei)
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Songti.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p

    # 尝试 fc-list
    try:
        out = subprocess.check_output(
            ["fc-list", ":lang=zh", "--format=%{file}\n"], timeout=5, text=True
        )
        fonts = [f.strip() for f in out.splitlines() if f.strip()]
        if fonts:
            return fonts[0]
    except Exception:
        pass
    return None


def make_summary_cover(
    ai_repos: list[dict], slot: str, today_cn: str, out_path: Path
) -> bool:
    """
    生成热榜总览封面图（1080×1080，白底黑字）。
    仿 GitHub Issue markdown 预览风格：每个 repo 两行
      行1: {rank}. owner/repo  · language · ★total · ▲today
      行2: description（缩进，浅灰）
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  ⚠️  Pillow not installed, skipping summary cover")
        return False

    try:
        import re as _re

        W, H   = 1080, 1080
        PAD    = 68
        # GitHub markdown preview 配色
        BG     = (255, 255, 255)
        DARK   = (36,  41,  47)    # 标题文字
        BLUE   = (9,  105, 218)    # repo 名（GitHub link blue）
        GOLD   = (154, 103,   0)   # ★ 总 stars（amber）
        GREEN  = (26,  127,  55)   # ▲ 今日涨幅
        ORANGE = (207,  87,  17)   # language
        GDESC  = (87,  96, 106)    # description
        META_G = (101, 109, 118)   # meta 分隔符 ·
        BORDER = (208, 215, 222)   # H2 下划线
        RED    = (207,  34,  46)   # 序号

        img  = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)

        font_path = find_cjk_font()

        def get_font(size: int):
            if font_path:
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    pass
            return ImageFont.load_default(size=size)

        def tw(text: str, font) -> int:
            b = draw.textbbox((0, 0), text, font=font)
            return b[2] - b[0]

        def th(text: str, font) -> int:
            b = draw.textbbox((0, 0), text, font=font)
            return b[3] - b[1]

        def truncate(text: str, font, max_px: int) -> str:
            if tw(text, font) <= max_px:
                return text
            while text:
                text = text[:-1]
                cand = text.rstrip() + "…"
                if tw(cand, font) <= max_px:
                    return cand
            return "…"

        def star_num(raw: str) -> str:
            m = _re.search(r"[\d,]+", raw)
            return m.group(0) if m else raw

        # ── H2 标题（GitHub ## 风格）──
        f_h2 = get_font(42)
        title = "今日 AI 热榜总览"
        draw.text((PAD, PAD), title, font=f_h2, fill=DARK)
        y = PAD + th(title, f_h2) + 10
        draw.line([PAD, y, W - PAD, y], fill=BORDER, width=1)
        y += 20

        # ── 字体 ──
        f_rank  = get_font(24)
        f_name  = get_font(27)
        f_meta  = get_font(20)
        f_desc  = get_font(20)
        f_brand = get_font(22)

        INDENT = PAD
        MAX_W  = W - PAD * 2

        # 计算动态行间距，让 8 个条目均匀填满画布
        NAME_ROW = th("Ag", f_name)
        DESC_ROW = th("Ag", f_desc)
        NAME_GAP = 5                         # name → desc 行间距
        BRAND_H  = th("#AI炼丹师", f_brand)
        avail    = H - y - PAD - BRAND_H - 10
        content  = (NAME_ROW + NAME_GAP + DESC_ROW) * len(ai_repos[:8])
        ITEM_GAP = max(8, (avail - content) // max(len(ai_repos[:8]) - 1, 1))

        list_y = y

        for idx, repo in enumerate(ai_repos[:8], 1):
            name     = repo.get("name", "")
            language = repo.get("language", "")
            s_total  = repo.get("stars_total", "")
            s_today  = star_num(repo.get("stars_today", ""))
            desc     = repo.get("description", "")

            # — 行1：序号(红) + repo名(蓝) + meta 彩色分段 —
            rank_str = f"{idx}."
            draw.text((INDENT, list_y), rank_str, font=f_rank, fill=RED)
            rank_w = tw(rank_str, f_rank)
            x_name = INDENT + rank_w + 6

            # 估算 meta 宽度后截断 repo 名
            meta_sample = f"  {language} · \u2605{s_total} · \u25b2{s_today}"
            meta_w_est  = tw(meta_sample, f_meta)
            name_max    = MAX_W - rank_w - 6 - meta_w_est - 4
            name_disp   = truncate(name, f_name, max(name_max, 80))
            draw.text((x_name, list_y - 1), name_disp, font=f_name, fill=BLUE)
            xm = x_name + tw(name_disp, f_name)

            # meta 彩色分段
            seg_y = list_y + (NAME_ROW - th("Ag", f_meta)) // 2 + 1
            pieces = [
                ("  ",              META_G),
                (language,          ORANGE),
                (" · ",             META_G),
                ("\u2605" + s_total, GOLD),
                (" · ",             META_G),
                ("\u25b2" + s_today, GREEN),
            ]
            xp = xm
            for txt, col in pieces:
                draw.text((xp, seg_y), txt, font=f_meta, fill=col)
                xp += tw(txt, f_meta)

            list_y += NAME_ROW + NAME_GAP

            # — 行2：description（深灰）—
            if desc:
                desc_disp = truncate(desc, f_desc, MAX_W - rank_w - 6)
                draw.text((x_name, list_y), desc_disp, font=f_desc, fill=GDESC)
            list_y += DESC_ROW + (ITEM_GAP if idx < len(ai_repos[:8]) else 0)

        # ── 底部品牌 ──
        f_brand = get_font(22)
        brand   = "#AI炼丹师"
        draw.text(
            ((W - tw(brand, f_brand)) // 2, H - PAD - BRAND_H),
            brand, font=f_brand, fill=META_G,
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_path), "PNG")
        return True

    except Exception as e:
        print(f"  ⚠️  make_summary_cover failed: {e}")
        return False


def make_post_body_cover(post: dict, index: int, out_path: Path) -> bool:
    """
    生成帖子正文封面图（1080×1080，白底黑字）。
    顶部序号徽章、两行封面标题、分割线、正文要点、底部品牌。
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  ⚠️  Pillow not installed, skipping post body cover")
        return False

    try:
        W, H   = 1080, 1080
        PAD    = 80
        RED    = (255, 45, 85)
        DARK   = (26, 26, 26)
        GRAY   = (140, 140, 140)
        LGRAY  = (240, 240, 240)
        WHITE  = (255, 255, 255)

        img  = Image.new("RGB", (W, H), WHITE)
        draw = ImageDraw.Draw(img)

        font_path = find_cjk_font()

        def get_font(size: int):
            if font_path:
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    pass
            return ImageFont.load_default(size=size)

        max_text_w = W - PAD * 2 - 30

        def fit_font(text: str, base_size: int, min_size: int = 48):
            """自动缩小字体直到文本适合宽度"""
            size = base_size
            while size >= min_size:
                f = get_font(size)
                bbox = draw.textbbox((0, 0), text, font=f)
                tw = bbox[2] - bbox[0]
                if tw <= max_text_w:
                    return f, tw, size
                size -= 6
            f = get_font(min_size)
            bbox = draw.textbbox((0, 0), text, font=f)
            return f, bbox[2] - bbox[0], min_size

        # ── 左侧红色竖条装饰 ──
        draw.rectangle([PAD - 12, PAD, PAD - 4, H - PAD], fill=RED)

        # ── 顶部序号徽章 ──
        badge_r = 36
        bx, by  = PAD + 30, PAD + 20
        draw.ellipse([bx, by, bx + badge_r * 2, by + badge_r * 2], fill=RED)
        draw.text(
            (bx + badge_r, by + badge_r), str(index),
            font=get_font(42), fill=WHITE, anchor="mm",
        )

        # ── 封面两行标题（居中） ──
        line1 = post.get("cover_line1", post.get("topic", "AI 热点"))
        line2 = post.get("cover_line2", TODAY_CN)

        title_y = PAD + badge_r * 2 + 50
        f1, tw1, sz1 = fit_font(line1, 90)
        draw.text(((W - tw1) // 2, title_y), line1, font=f1, fill=DARK)

        title_y += sz1 + 20
        f2, tw2, sz2 = fit_font(line2, 68)
        draw.text(((W - tw2) // 2, title_y), line2, font=f2, fill=DARK)

        # ── 分割线 ──
        line_y = title_y + sz2 + 30
        draw.line([PAD + 30, line_y, W - PAD - 30, line_y], fill=LGRAY, width=2)

        # ── 正文要点提取 ──
        EMOJI_NUMS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣")
        body       = post.get("body", "")
        body_lines = body.split("\n")

        key_lines = [ln for ln in body_lines if any(ln.startswith(e) for e in EMOJI_NUMS)]

        if key_lines:
            points = []
            for ln in key_lines[:4]:
                # 去掉首个 emoji（unicode emoji 可能占多个字符，按空格切）
                stripped = ln
                for e in EMOJI_NUMS:
                    if stripped.startswith(e):
                        stripped = stripped[len(e):].lstrip()
                        break
                if len(stripped) > 24:
                    stripped = stripped[:24] + "…"
                points.append(stripped)
        else:
            # 无 emoji 序号行，取 body 前 3 行
            points = [ln.strip() for ln in body_lines if ln.strip()][:3]
            points = [p[:24] + "…" if len(p) > 24 else p for p in points]

        f_point = get_font(30)
        pt_y    = line_y + 24
        pt_gap  = 30 + 12    # 字号 + 行间距

        for pt in points:
            draw.text((PAD + 30, pt_y), f"• {pt}", font=f_point, fill=DARK)
            pt_y += pt_gap

        # ── 底部：品牌 + 日期 ──
        footer_y = H - PAD - 60
        brand    = "AI 小红书日报"
        f_brand  = get_font(32)
        bbox     = draw.textbbox((0, 0), brand, font=f_brand)
        draw.text(((W - (bbox[2] - bbox[0])) // 2, footer_y), brand, font=f_brand, fill=RED)

        date_str = f"· {TODAY_CN} ·"
        f_date   = get_font(26)
        bbox     = draw.textbbox((0, 0), date_str, font=f_date)
        draw.text(
            ((W - (bbox[2] - bbox[0])) // 2, footer_y + 40),
            date_str, font=f_date, fill=GRAY,
        )

        # ── 右下角 watermark ──
        watermark = "#AI炼丹师"
        f_wm      = get_font(26)
        bbox      = draw.textbbox((0, 0), watermark, font=f_wm)
        draw.text(
            (W - PAD - (bbox[2] - bbox[0]), H - PAD - 30),
            watermark, font=f_wm, fill=GRAY,
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_path), "PNG")
        return True

    except Exception as e:
        print(f"  ⚠️  make_post_body_cover failed: {e}")
        return False


def get_default_branch(owner: str, repo: str) -> str:
    """获取仓库默认分支名（master 或 main）。"""
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept":        "application/vnd.github.v3+json",
            },
            timeout=10,
        )
        return resp.json().get("default_branch", "main")
    except Exception:
        return "main"


# ══════════════════════════════════════════════════════════════════════════════
# 1. 抓取 GitHub Trending（每日榜）
# ══════════════════════════════════════════════════════════════════════════════

def fetch_github_trending(since: str = "daily", top_n: int = 10) -> list[dict]:
    """
    抓取 GitHub Trending 当日榜 Top N，返回所有语言的仓库列表。
    since: daily | weekly | monthly
    """
    url     = f"https://github.com/trending?since={since}"
    headers = {"Accept": "text/html", "User-Agent": "Mozilla/5.0 (compatible; trending-bot)"}

    print(f"📡 Fetching GitHub Trending ({since})…")
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ⚠️  Trending fetch failed: {e}")
        return []

    soup  = BeautifulSoup(resp.text, "lxml")
    repos = []

    for article in soup.select("article.Box-row")[:top_n]:
        # ── 仓库名 ──
        a_tag    = article.select_one("h2 a")
        if not a_tag:
            continue
        full_name = a_tag["href"].lstrip("/").strip()   # owner/repo
        repo_url  = f"https://github.com/{full_name}"

        # ── 描述 ──
        desc_tag = article.select_one("p")
        desc     = desc_tag.get_text(strip=True) if desc_tag else ""

        # ── 主语言 ──
        lang_tag = article.select_one("[itemprop='programmingLanguage']")
        language = lang_tag.get_text(strip=True) if lang_tag else ""

        # ── 今日 Stars ──
        stars_today = ""
        for span in article.select("span.d-inline-block"):
            t = span.get_text(strip=True)
            if "stars today" in t or "star today" in t:
                stars_today = t.replace("\n", "").strip()
                break

        # ── 总 Stars ──
        stars_total = ""
        a_stars = article.select("a.Link--muted")
        for a in a_stars:
            href = a.get("href", "")
            if "stargazers" in href:
                stars_total = a.get_text(strip=True)
                break

        repos.append({
            "name":        full_name,
            "url":         repo_url,
            "description": desc,
            "language":    language,
            "stars_today": stars_today,
            "stars_total": stars_total,
        })

    print(f"  ✅ {len(repos)} repos fetched from Trending")
    return repos


def filter_ai_repos(repos: list[dict]) -> list[dict]:
    """从 trending 列表中筛选 AI 相关仓库。"""
    results = []
    for repo in repos:
        text = " ".join([
            repo["name"].lower(),
            repo["description"].lower(),
        ])
        if any(kw in text for kw in AI_KEYWORDS):
            results.append(repo)

    print(f"  🤖 {len(results)} AI-related repos after filtering")
    return results


# ══════════════════════════════════════════════════════════════════════════════
# 2. LLM 生成小红书风格内容
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """\
你是小红书头部 AI 科技博主「AI炼丹师」，专注 AI 技术科普，粉丝 50w+。

【封面标题铁律 — 两行结构】
第一行（≤10字）= 「钩子」：制造悬念/冲突/好奇，绝不写结论，不用句号
第二行（≤12字）= 「揭晓/强化」：补充关键信息或情绪反转，用「！」或「…」结尾
禁止：两行都是完整句；两行都是问句；两行主题不一致

【标题人名/公司锚点优先级（按效果排序）】
① 知名人物点名 — 马斯克、黄仁勋、Sam Altman、LeCun、Hinton、Pichai、苏姿丰
② 大公司竞争对比 — OpenAI vs 谷歌/Meta/Anthropic/苹果/微软
③ 明星产品对决 — ChatGPT vs Claude vs Gemini vs Copilot vs Llama
④ 以上都没有时，用数字体或「偷偷/悄悄」内幕体

【5大爆款标题公式】
公式1 人名+惊人行为：「[名人]偷偷做了这件事 / [名人]这句话让全场沉默」
公式2 产品战争体：「[产品A]这次真的[吊打/暴打/超越]了 / [产品B]彻底慌了！」
公式3 身份反差体：「[高薪职业/年限] / 被$0 AI替了」
公式4 数字实测体：「我用AI[时间][做了什么] / [N]倍速！结果出乎意料」
公式5 内幕悄悄体：「[大公司]悄悄上线了 / 90%用户还不知道！」

【情绪触发词必选一个】
冲击词：爆了/炸了/王炸/暴打/碾压/吊打
好奇词：偷偷/悄悄/内部/泄露/隐藏/没公开
反差词：竟然/没想到/原来/但其实
亲测词：实测/亲测/踩坑/真的能/N倍

【正文结构】
1️⃣ 开头钩子（1-2句）：用「刚看到」「实测完成」「你不知道的是」「圈内没人说破的」开头；禁用「今天」「最近」「现在」等模糊时间词
2️⃣ 核心干货（3-5点，emoji序号，每点2-3行）
3️⃣ 实用价值（能做什么/怎么用/有什么影响）
4️⃣ 互动结尾（一个具体问题引发评论，或"关注不迷路"）

【语言风格】
口语化中文，不装，不端着，技术词保留英文原文
禁止：废话开头、过度宣传词、一段话超过5行、标题与正文内容不符
"""

USER_PROMPT_TEMPLATE = """\
以下是今日 GitHub Trending AI 热门项目（JSON）：

{repos_json}

从中挑选最有价值的项目（最多 {count} 个，优先选：Star 增长猛、应用场景新颖、涉及知名公司/模型）。
为每个项目生成一篇小红书帖子，重点突出「这个项目能帮你做什么」「为什么今天突然爆火」。

封面标题要求：
- 若项目来自 OpenAI/Google/Meta/Anthropic/Microsoft/Apple，优先对比战争体
- 若涉及知名人物，第一行点名
- 否则用数字体（「GitHub今日涨{{N}}星」「程序员偷偷在用的」）或内幕悄悄体

输出格式：合法 JSON 数组，不含任何其他文字。
[
  {{
    "topic": "项目简短名（10字以内）",
    "repo": "owner/repo",
    "cover_line1": "封面第一行（≤10字，钩子/悬念，不写结论，不用句号）",
    "cover_line2": "封面第二行（≤12字，揭晓/反转/强化，用！或…结尾）",
    "body": "正文（含emoji、分段、干货、互动结尾，300-500字）",
    "tags": ["标签1","标签2","标签3","标签4","标签5","标签6","标签7","标签8","标签9","标签10"]
  }}
]
"""


def generate_posts_with_llm(ai_repos: list[dict], max_posts: int = 4) -> list[dict]:
    if not LLM_API_KEY:
        print("  ⚠️  LLM_API_KEY not set, using fallback")
        return _fallback_posts(ai_repos, max_posts)

    count = min(len(ai_repos), max_posts)
    if count == 0:
        print("  ⚠️  No AI repos to generate posts for")
        return []

    print(f"✍️  Generating {count} posts with LLM…")
    prompt = USER_PROMPT_TEMPLATE.format(
        repos_json=json.dumps(ai_repos, ensure_ascii=False, indent=2),
        count=count,
    )

    try:
        resp = requests.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model":       LLM_MODEL,
                "messages":    [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                "temperature": 0.9,
                "max_tokens":  4096,
            },
            timeout=90,
        )
        resp_json = resp.json()
        if "choices" not in resp_json:
            print(f"  ⚠️  Unexpected API response: {json.dumps(resp_json)[:300]}")
            return _fallback_posts(ai_repos, max_posts)

        raw   = resp_json["choices"][0]["message"]["content"].strip()
        start = raw.find("[")
        end   = raw.rfind("]") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

        posts = json.loads(raw)
        print(f"  ✅ {len(posts)} posts generated")
        return posts[:max_posts]

    except Exception as e:
        print(f"  ⚠️  LLM generation failed: {e}")
        return _fallback_posts(ai_repos, max_posts)


def _fallback_posts(repos: list[dict], max_posts: int) -> list[dict]:
    posts = []
    for repo in repos[:max_posts]:
        name = repo.get("name", "unknown/repo")
        desc = repo.get("description", "")
        posts.append({
            "topic":       name.split("/")[-1][:20],
            "repo":        name,
            "cover_line1": name.split("/")[-1][:10],
            "cover_line2": f"今日 GitHub 热榜！",
            "body": (
                f"🔥 GitHub Trending 今日爆款来了！\n\n"
                f"**{name}**\n\n"
                f"📌 {desc}\n\n"
                f"🔗 https://github.com/{name}\n\n"
                f"关注我，每天第一时间 AI 动态 👇"
            ),
            "tags": ["AI","GitHub","开源","热门项目","大模型",
                     "机器学习","深度学习","AI工具","技术","炼丹"],
        })
    return posts


# ══════════════════════════════════════════════════════════════════════════════
# 3. GitHub Issue 创建
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_labels(owner: str, repo: str) -> None:
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github.v3+json",
    }
    for label, color, desc in [
        ("trending",    "0e8a16", "GitHub Trending AI hot picks"),
        ("ai-content",  "e4e669", "AI-generated content"),
        ("daily-post",  "0075ca", "Auto-generated daily AI post"),
    ]:
        try:
            requests.post(
                f"https://api.github.com/repos/{owner}/{repo}/labels",
                headers=headers,
                json={"name": label, "color": color, "description": desc},
                timeout=10,
            )
        except Exception:
            pass


def build_issue_body(
    posts: list[dict],
    all_repos: list[dict],
    ai_repos: list[dict],
    image_paths: list[str | None] | None = None,
    branch: str = "main",
) -> str:
    image_paths = image_paths or []
    parts = [
        f"# 🔥 GitHub Trending AI {SLOT} · {TODAY_CN}",
        "",
        f"> 由 GitHub Actions 自动生成 · 数据来源：GitHub Trending（每日榜）",
        "",
        "---",
        "",
        "## 📊 今日 AI 热榜总览",
        "",
    ]

    # 总览封面图
    summary_img = image_paths[0] if image_paths else None
    if summary_img and GITHUB_REPO:
        raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{branch}/{summary_img}"
        parts += [f"![trending-summary]({raw_url})", ""]

    # 全部 AI 项目汇总表格
    for i, repo in enumerate(ai_repos, 1):
        lang       = f" · {repo['language']}" if repo.get("language") else ""
        stars_line = f" · ⭐ {repo['stars_total']}" if repo.get("stars_total") else ""
        today_line = f" · 🔺 {repo['stars_today']}" if repo.get("stars_today") else ""
        parts.append(
            f"{i}. **[{repo['name']}](https://github.com/{repo['name']})**"
            f"{lang}{stars_line}{today_line}"
        )
        if repo.get("description"):
            parts.append(f"   _{repo['description']}_")
        parts.append("")

    parts += ["---", ""]

    # 精选帖子详情（image_paths[1:] 对应各帖子图，index 0 是 summary）
    post_imgs = image_paths[1:] if len(image_paths) > 1 else []

    for i, post in enumerate(posts, 1):
        repo_link = f"https://github.com/{post.get('repo', '')}" if post.get("repo") else ""
        line1     = post.get("cover_line1", "")
        line2     = post.get("cover_line2", "")

        parts.append(f"## 帖子 {i} · {post.get('topic', '')}")
        if repo_link:
            parts.append(f"> 🔗 [{post.get('repo','')}]({repo_link})")
        parts.append("")

        # 封面标题
        parts += ["**📌 封面标题：**", "```", line1, line2, "```", ""]

        # 帖子正文封面图
        post_img = post_imgs[i - 1] if i - 1 < len(post_imgs) else None
        if post_img and GITHUB_REPO:
            raw_url = (
                f"https://raw.githubusercontent.com/{GITHUB_REPO}/{branch}/{post_img}"
            )
            parts += [f"**🖼️ 封面图：**", f"![post{i}]({raw_url})", ""]

        # 正文
        parts += ["**📝 正文：**", "", post.get("body", ""), ""]

        # 标签
        tags    = post.get("tags", [])
        tag_str = "  ".join(f"`#{t}`" for t in tags)
        parts  += [f"**🏷️ 话题标签：** {tag_str}", "", "---", ""]

    parts += [
        f"<sub>✨ Generated by [ai-xiaohongshu-daily]"
        f"(https://github.com/{GITHUB_REPO or 'your/repo'}) · "
        f"Slot: {SLOT} {TODAY} {HOUR}:00</sub>",
    ]
    return "\n".join(parts)


def create_github_issue(
    posts: list[dict],
    all_repos: list[dict],
    ai_repos: list[dict],
    image_paths: list[str | None] | None = None,
) -> str | None:
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("  ⚠️  GITHUB_TOKEN / GITHUB_REPOSITORY not set, skipping")
        return None

    owner, repo = GITHUB_REPO.split("/", 1)
    _ensure_labels(owner, repo)
    branch = get_default_branch(owner, repo)
    print(f"  🌿 Default branch: {branch}")

    body    = build_issue_body(posts, all_repos, ai_repos, image_paths=image_paths, branch=branch)
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github.v3+json",
    }

    title = f"🔥 GitHub Trending AI {SLOT} · {TODAY} · Top {len(ai_repos)} 项目"
    print(f"📝 Creating GitHub Issue: {title}")

    try:
        resp = requests.post(
            f"https://api.github.com/repos/{owner}/{repo}/issues",
            headers=headers,
            json={
                "title":  title,
                "body":   body,
                "labels": ["trending", "ai-content"],
            },
            timeout=30,
        )
        if resp.status_code == 201:
            url = resp.json()["html_url"]
            print(f"  ✅ Issue created: {url}")
            return url
        else:
            print(f"  ❌ Failed: {resp.status_code} {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"  ❌ Exception: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 4. 飞书通知（每个帖子一条消息）
# ══════════════════════════════════════════════════════════════════════════════

def send_feishu_notify(posts: list[dict], issue_url: str | None = None) -> None:
    if not FEISHU_WEBHOOK:
        print("  ⚠️  FEISHU_WEBHOOK not set, skipping")
        return

    print("📨 Sending Feishu notifications…")

    # 先发一条汇总头
    header_text = (
        f"🔥 GitHub Trending AI {SLOT} · {TODAY_CN}\n"
        f"共 {len(posts)} 个精选项目"
    )
    if issue_url:
        header_text += f"\n📋 Issue：{issue_url}"

    try:
        requests.post(
            FEISHU_WEBHOOK,
            json={"msg_type": "text", "content": {"text": header_text}},
            timeout=10,
        )
    except Exception as e:
        print(f"  ⚠️  Header notify failed: {e}")

    # 每个帖子一条
    for i, post in enumerate(posts, 1):
        topic   = post.get("topic", f"帖子{i}")
        line1   = post.get("cover_line1", "")
        line2   = post.get("cover_line2", "")
        body    = post.get("body", "")
        tags    = post.get("tags", [])
        repo    = post.get("repo", "")
        tag_str = " ".join(f"#{t}" for t in tags)

        text = (
            f"🔥 Trending {SLOT} · 帖子{i}/{len(posts)} · {topic}\n"
            f"{'─' * 36}\n"
        )
        if repo:
            text += f"📦 github.com/{repo}\n\n"
        text += (
            f"🎨 封面标题\n{line1}\n{line2}\n\n"
            f"📝 正文\n{body}\n\n"
            f"🏷️ 标签\n{tag_str}"
        )

        try:
            resp   = requests.post(
                FEISHU_WEBHOOK,
                json={"msg_type": "text", "content": {"text": text}},
                timeout=10,
            )
            result = resp.json()
            if resp.status_code == 200 and result.get("code") == 0:
                print(f"  ✅ 帖子{i} ({topic}) 已发送")
            else:
                print(f"  ⚠️  帖子{i} 发送失败: {result.get('msg', resp.text[:120])}")
        except Exception as e:
            print(f"  ⚠️  帖子{i} 发送异常: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 5. 飞书图片链接通知
# ══════════════════════════════════════════════════════════════════════════════

def send_feishu_images(
    image_paths: list[str | None],
    posts: list[dict],
    slot: str,
    today_cn: str,
) -> None:
    """依次把每张封面图的 GitHub raw URL 发到飞书（一图一条消息）。"""
    if not FEISHU_WEBHOOK:
        print("  ⚠️  FEISHU_WEBHOOK not set, skipping image notify")
        return
    if not GITHUB_REPO:
        print("  ⚠️  GITHUB_REPOSITORY not set, skipping image notify")
        return

    owner, repo = GITHUB_REPO.split("/", 1)
    branch      = get_default_branch(owner, repo)

    n_posts = len(posts)
    # image_paths[0] = summary, image_paths[1:] = post covers
    labels: list[str] = [f"📊 今日 AI 热榜总览"]
    for i, post in enumerate(posts, 1):
        topic = post.get("cover_line1", post.get("topic", f"帖子{i}"))
        labels.append(f"🖼️ 帖子{i}/{n_posts} · {topic}")

    print("📨 Sending Feishu image notifications…")
    for idx, path in enumerate(image_paths):
        if not path:
            continue
        label   = labels[idx] if idx < len(labels) else f"🖼️ 图片{idx}"
        raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{branch}/{path}"
        text    = f"{label}\n{raw_url}"
        try:
            resp   = requests.post(
                FEISHU_WEBHOOK,
                json={"msg_type": "text", "content": {"text": text}},
                timeout=10,
            )
            result = resp.json()
            if resp.status_code == 200 and result.get("code") == 0:
                print(f"  ✅ 图片{idx} ({label}) 已发送")
            else:
                print(f"  ⚠️  图片{idx} 发送失败: {result.get('msg', resp.text[:120])}")
        except Exception as e:
            print(f"  ⚠️  图片{idx} 发送异常: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 6. 主流程（分阶段）
# ══════════════════════════════════════════════════════════════════════════════

def phase_generate(since: str = "daily", top_n: int = 10, max_posts: int = 4) -> None:
    """阶段一：抓取 → AI过滤 → LLM生成帖子 → 生成封面图 → 保存 trending_data.json"""
    print(f"\n🚀 [generate] GitHub Trending AI {SLOT}  [{TODAY} {HOUR}:xx]\n{'─'*54}")

    # 1. 抓取 Trending
    all_repos = fetch_github_trending(since=since, top_n=top_n)
    if not all_repos:
        print("❌ No repos fetched. Exiting.")
        sys.exit(1)

    # 2. 过滤 AI 项目
    ai_repos = filter_ai_repos(all_repos)
    if not ai_repos:
        print("ℹ️  No AI repos found in today's Trending. Creating placeholder issue.")
        ai_repos = all_repos[:3]   # 保底取前 3 个

    # 3. LLM 生成小红书帖子
    posts = generate_posts_with_llm(ai_repos, max_posts=max_posts)
    if not posts:
        print("❌ No posts generated. Exiting.")
        sys.exit(1)

    # 4. 生成封面图
    print("🎨 Generating trending cover images (Pillow)…")
    trending_dir  = ASSETS_DIR / "trending"
    image_paths: list[str | None] = []

    # 4a. 热榜总览封面图
    summary_path = trending_dir / "summary.png"
    ok = make_summary_cover(ai_repos, SLOT, TODAY_CN, summary_path)
    if ok:
        print(f"  ✅ summary.png → {summary_path}")
        image_paths.append(str(summary_path))
    else:
        image_paths.append(None)

    # 4b. 各帖子正文封面图
    for i, post in enumerate(posts, 1):
        post_path = trending_dir / f"post{i}.png"
        ok = make_post_body_cover(post, i, post_path)
        if ok:
            print(f"  ✅ post{i}.png → {post_path}")
            image_paths.append(str(post_path))
        else:
            image_paths.append(None)

    # 5. 保存中间数据（含 image_paths 字段）
    DATA_FILE.write_text(
        json.dumps(
            {
                "date":        TODAY,
                "slot":        SLOT,
                "all_repos":   all_repos,
                "ai_repos":    ai_repos,
                "posts":       posts,
                "image_paths": image_paths,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"💾 Saved {DATA_FILE}")
    print(f"\n✅ [generate] Done — {len(posts)} posts, {len([p for p in image_paths if p])} images")


def phase_publish() -> None:
    """阶段二：读取 trending_data.json → 创建 Issue → 发飞书文字通知 → 发飞书图片链接"""
    print(f"\n🚀 [publish] GitHub Trending AI {SLOT}  [{TODAY} {HOUR}:xx]\n{'─'*54}")

    if not DATA_FILE.exists():
        print(f"❌ {DATA_FILE} not found. Run --phase generate first.")
        sys.exit(1)

    data      = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    all_repos = data.get("all_repos", [])
    ai_repos  = data.get("ai_repos", [])
    posts     = data.get("posts", [])
    image_paths: list[str | None] = data.get("image_paths", [])

    # 1. 创建 GitHub Issue
    issue_url = create_github_issue(posts, all_repos, ai_repos, image_paths=image_paths)

    # 2. 飞书文字通知
    send_feishu_notify(posts, issue_url)

    # 3. 飞书图片链接通知
    send_feishu_images(image_paths, posts, SLOT, TODAY_CN)

    print(f"\n✅ [publish] Done — {len(posts)} posts published")


def main() -> None:
    parser = argparse.ArgumentParser(description="GitHub Trending AI 追踪器")
    parser.add_argument("--since",     default="daily",  choices=["daily", "weekly", "monthly"])
    parser.add_argument("--top-n",     default=10,  type=int, help="抓取 Trending 条数")
    parser.add_argument("--max-posts", default=4,   type=int, help="最多生成帖子数")
    parser.add_argument(
        "--phase",
        default="all",
        choices=["generate", "publish", "all"],
        help="执行阶段：generate=抓取+生图, publish=发Issue+飞书, all=顺序执行两阶段（默认）",
    )
    args = parser.parse_args()

    if args.phase == "generate":
        phase_generate(since=args.since, top_n=args.top_n, max_posts=args.max_posts)
    elif args.phase == "publish":
        phase_publish()
    else:  # all
        phase_generate(since=args.since, top_n=args.top_n, max_posts=args.max_posts)
        phase_publish()


if __name__ == "__main__":
    main()
