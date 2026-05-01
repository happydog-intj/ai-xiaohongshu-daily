#!/usr/bin/env python3
"""
AI 日报生成器
每天自动抓取 AI 热点，生成小红书风格内容 + 白底黑字封面图，发布为 GitHub Issue
"""

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

# ── 时区 & 常量 ────────────────────────────────────────────────────────────────
CST     = timezone(timedelta(hours=8))
TODAY   = datetime.now(CST).strftime("%Y-%m-%d")
TODAY_CN= datetime.now(CST).strftime("%Y.%m.%d")

ASSETS_DIR = Path("assets") / TODAY

AI_KEYWORDS = {
    "ai", "llm", "gpt", "claude", "gemini", "agent", "openai",
    "anthropic", "deepmind", "mistral", "llama", "model", "neural",
    "diffusion", "transformer", "rag", "fine-tun", "multimodal",
}

# ── 环境变量 ────────────────────────────────────────────────────────────────────
LLM_API_KEY  = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_MODEL    = os.environ.get("LLM_MODEL", "gpt-4o-mini")
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO    = os.environ.get("GITHUB_REPOSITORY", "")   # owner/repo
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")      # 飞书自定义机器人 Webhook URL

# XHS 品牌红
XHS_RED  = "#FF2D55"
XHS_DARK = "#1A1A1A"


# ══════════════════════════════════════════════════════════════════════════════
# 1. 数据抓取
# ══════════════════════════════════════════════════════════════════════════════

def fetch_hackernews_ai(limit: int = 6) -> list[dict]:
    print("📡 Fetching HackerNews…")
    try:
        ids = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10
        ).json()[:60]
    except Exception as e:
        print(f"  ⚠️  HN fetch failed: {e}")
        return []

    stories = []
    for sid in ids:
        if len(stories) >= limit:
            break
        try:
            item = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=6
            ).json()
            title = (item.get("title") or "").lower()
            if any(kw in title for kw in AI_KEYWORDS):
                stories.append({
                    "source": "HackerNews",
                    "title":  item.get("title", ""),
                    "url":    item.get("url", ""),
                    "score":  item.get("score", 0),
                })
        except Exception:
            pass

    print(f"  ✅ {len(stories)} HN stories")
    return stories


def fetch_github_trending_ai(limit: int = 6) -> list[dict]:
    print("📡 Fetching GitHub Trending…")
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    headers  = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        resp = requests.get(
            "https://api.github.com/search/repositories",
            params={
                "q":        f"topic:ai OR topic:llm created:>{week_ago}",
                "sort":     "stars",
                "order":    "desc",
                "per_page": limit,
            },
            headers=headers, timeout=12,
        )
        repos = []
        for r in resp.json().get("items", []):
            repos.append({
                "source":      "GitHub",
                "name":        r["full_name"],
                "stars":       r["stargazers_count"],
                "description": r.get("description") or "",
                "url":         r["html_url"],
            })
        print(f"  ✅ {len(repos)} GitHub repos")
        return repos
    except Exception as e:
        print(f"  ⚠️  GitHub fetch failed: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# 2. LLM 生成内容（爆款小红书风格）
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """\
你是小红书头部 AI 科技博主「AI炼丹师」，专注 AI 技术科普，粉丝 50w+。

【封面标题铁律 — 两行结构】
第一行（≤10字）= 「钩子」：制造悬念/冲突/好奇，绝不写结论，不用句号
第二行（≤12字）= 「揭晓/强化」：补充关键信息或情绪反转，用「！」或「…」结尾
禁止：两行都是完整句；两行都是问句；两行主题不一致

【标题人名/公司锚点优先级（按效果排序）】
① 知名人物点名优先 — 马斯克、黄仁勋、Sam Altman、LeCun、Hinton、Pichai、苏姿丰
② 大公司竞争写成对比体 — OpenAI vs 谷歌/Meta/Anthropic/苹果/微软
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

【正文风格 — ljg-plain 白话原则】
正文是一篇从头流到尾的连贯文字，不用编号分点，不用小标题。像跟一个聪明朋友说话，让他一下子 grok（懂透）这件事。

九条铁律：
① 口语检验——读出声来，你会这样跟朋友说吗？不会就改到会
② 零术语——专业词必须先用大白话把意思落地，再顺带提出名字
③ 短词优先——能两个字说的不用四个字；「进行分析」→「看」
④ 一句一事——每句只推进一步，长句拆短
⑤ 具体——名词看得见，动词有力气；「情况不太好」→「项目三天没人提交代码」
⑥ 开头给理由——第一句让人想读下一句，不铺垫、不「自古以来」
⑦ 不填充——删开场白、拐杖词。每句都在干活
⑧ 信任读者——说一遍够了，不反复解释，不加手把手引导
⑨ 诚实——「大概 70%」比「可能」诚实；想不清楚就说想不清楚

结尾用一个真问题收尾（读者真的会想回答的那种），不用套路互动公式。
"""

USER_PROMPT_TEMPLATE = """\
今天是{today}，以下是今日 AI 圈热点（JSON）：

{topics}

从中挑选最有价值的 **4 个**话题（优先：涉及知名人物/大公司竞争/明星产品的新颖动态）。
为每个生成一篇小红书帖子。

封面标题要求：
- 若话题涉及 马斯克/黄仁勋/Altman/LeCun/Hinton/Pichai，第一行必须点名该人物
- 若涉及 OpenAI/谷歌/苹果/Meta/Anthropic/微软 之间的竞争，优先写成对比战争体
- 否则使用数字体或内幕悄悄体

输出格式：合法 JSON 数组，不要有其他任何文字。
[
  {{
    "topic": "话题简短名（10字以内）",
    "cover_line1": "封面第一行（≤10字，钩子/悬念/冲突，不写结论，不用句号）",
    "cover_line2": "封面第二行（≤12字，揭晓/反转/强化，用！或…结尾）",
    "body": "正文（ljg-plain 白话风格，连贯散文，不分点不加标题，300-500字，结尾一个真问题）",
    "tags": ["标签1","标签2","标签3","标签4","标签5","标签6","标签7","标签8","标签9","标签10"]
  }}
]
"""


# 套路开头/结尾清单 — 与 SYSTEM_PROMPT 中的禁止词保持一致
_FORBIDDEN_OPENERS = [
    "刚看到", "实测完成", "实测刚完成", "你不知道的是",
    "圈内没人说破的", "圈内没人说破", "这件事没人告诉你",
]
_FORBIDDEN_TAIL_RE = re.compile(
    r"(关注不迷路|下期预告|下期拆解|下期发|下期带|关注我.{0,4}不迷路)[^\n]*\n?"
)


def _scrub_forbidden_phrases(text: str) -> str:
    """移除 LLM 偶尔仍会输出的套路开头/结尾，确保产出符合品牌规范。"""
    if not text:
        return text

    # 1) 逐段去除开头的套路词（兼容前导空白/标点）
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        prefix = line[: len(line) - len(stripped)]
        for opener in _FORBIDDEN_OPENERS:
            if stripped.startswith(opener):
                rest = stripped[len(opener):].lstrip("：:，,。.！!～~ \t")
                stripped = rest
                break
        cleaned_lines.append(prefix + stripped)
    text = "\n".join(cleaned_lines)

    # 2) 去除结尾「关注不迷路 / 下期预告」这类公式
    text = _FORBIDDEN_TAIL_RE.sub("", text)

    return text.rstrip() + ("\n" if text.endswith("\n") else "")


def _sanitize_posts(posts: list[dict]) -> list[dict]:
    for post in posts:
        if isinstance(post.get("body"), str):
            post["body"] = _scrub_forbidden_phrases(post["body"])
    return posts


def generate_posts_with_llm(topics: dict) -> list[dict]:
    if not LLM_API_KEY:
        print("  ⚠️  LLM_API_KEY not set, using fallback template")
        return _fallback_posts(topics)

    print("✍️  Generating content with LLM…")
    prompt = USER_PROMPT_TEMPLATE.format(
        today=TODAY_CN,
        topics=json.dumps(topics, ensure_ascii=False, indent=2),
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
            return _fallback_posts(topics)

        raw = resp_json["choices"][0]["message"]["content"].strip()
        start = raw.find("[")
        end   = raw.rfind("]") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

        posts = json.loads(raw)
        posts = _sanitize_posts(posts[:4])
        print(f"  ✅ {len(posts)} posts generated")
        return posts

    except Exception as e:
        print(f"  ⚠️  LLM generation failed: {e}")
        return _sanitize_posts(_fallback_posts(topics))


def _fallback_posts(topics: dict) -> list[dict]:
    items = topics.get("hackernews", []) + topics.get("github_trending", [])
    posts = []
    for item in items[:4]:
        title = item.get("title") or item.get("name", "AI 热点")
        posts.append({
            "topic":      title[:20],
            "cover_line1": title[:10],
            "cover_line2": "今日 AI 热点速报",
            "body": (
                f"🔥 今日 AI 圈又炸了！\n\n"
                f"**{title}**\n\n"
                f"📌 来源：{item.get('source','')}\n"
                f"🔗 {item.get('url', item.get('description',''))}\n\n"
                f"关注我，每天第一时间 AI 动态 👇"
            ),
            "tags": ["AI","人工智能","大模型","科技","每日热点",
                     "机器学习","深度学习","AI工具","技术","炼丹"],
        })
    return posts


# ══════════════════════════════════════════════════════════════════════════════
# 3. 封面图生成（Pillow · 白底黑字）
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


def make_cover_image(line1: str, line2: str, index: int, out_path: Path) -> bool:
    """生成白底黑字封面图（1080×1080），返回是否成功"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  ⚠️  Pillow not installed, skipping cover image")
        return False

    W, H   = 1080, 1080
    PAD    = 80
    RED    = (255, 45, 85)      # #FF2D55
    DARK   = (26, 26, 26)       # #1A1A1A
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

    # ── 背景装饰：左上角红色竖条 ──
    draw.rectangle([PAD - 12, PAD, PAD - 4, H - PAD], fill=RED)

    # ── 顶部序号徽章 ──
    badge_r = 36
    bx, by  = PAD + 30, PAD + 20
    draw.ellipse([bx, by, bx + badge_r*2, by + badge_r*2], fill=RED)
    draw.text(
        (bx + badge_r, by + badge_r), str(index),
        font=get_font(42), fill=WHITE, anchor="mm",
    )

    # ── 标题两行（居中，主体区域） ──
    title_y  = H // 2 - 100
    max_text_w = W - PAD * 2 - 30   # 最大文本宽度

    def fit_font(text: str, base_size: int, min_size: int = 48) -> tuple:
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

    # 行1 — 更大更粗
    f1, tw1, sz1 = fit_font(line1, 108)
    draw.text(((W - tw1) // 2, title_y), line1, font=f1, fill=DARK)

    # 行2
    title_y += sz1 + 28
    f2, tw2, sz2 = fit_font(line2, 80)
    draw.text(((W - tw2) // 2, title_y), line2, font=f2, fill=DARK)

    # ── 分割线 ──
    line_y = title_y + sz2 + 40
    draw.line([PAD + 30, line_y, W - PAD - 30, line_y], fill=LGRAY, width=2)

    # ── 底部：品牌 + 日期 ──
    footer_y = H - PAD - 50
    brand    = "AI 日报"
    f_brand  = get_font(38)
    bbox     = draw.textbbox((0, 0), brand, font=f_brand)
    draw.text(((W - (bbox[2]-bbox[0])) // 2, footer_y), brand, font=f_brand, fill=RED)

    date_str = f"· {TODAY_CN} ·"
    f_date   = get_font(30)
    bbox     = draw.textbbox((0, 0), date_str, font=f_date)
    draw.text(((W - (bbox[2]-bbox[0])) // 2, footer_y + 50), date_str, font=f_date, fill=GRAY)

    # ── 右下角小字 ──
    watermark = "#AI炼丹师"
    f_wm      = get_font(28)
    bbox      = draw.textbbox((0, 0), watermark, font=f_wm)
    draw.text((W - PAD - (bbox[2]-bbox[0]), H - PAD - 30), watermark, font=f_wm, fill=GRAY)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), "PNG")
    return True


def generate_cover_images(posts: list[dict]) -> list[str | None]:
    """为所有帖子生成封面图"""
    print("🎨 Generating cover images (Pillow)…")
    image_paths: list[str | None] = []

    for i, post in enumerate(posts, 1):
        line1 = post.get("cover_line1", post.get("topic", "AI 热点"))
        line2 = post.get("cover_line2", TODAY_CN)
        dest  = ASSETS_DIR / f"cover{i}.png"

        ok = make_cover_image(line1, line2, i, dest)
        if ok:
            print(f"  ✅ cover{i}.png → {line1} / {line2}")
            image_paths.append(str(dest))
        else:
            image_paths.append(None)

    return image_paths


# ══════════════════════════════════════════════════════════════════════════════
# 4. GitHub Issue 创建
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_labels(owner: str, repo: str) -> None:
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github.v3+json",
    }
    for label, color, desc in [
        ("daily-post", "0075ca", "Auto-generated daily AI post"),
        ("ai-content", "e4e669", "AI-generated content"),
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


def get_default_branch(owner: str, repo: str) -> str:
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


def build_issue_body(
    posts: list[dict], image_paths: list[str | None], branch: str = "main"
) -> str:
    parts = [
        f"# 🤖 AI 日报 · {TODAY_CN}",
        "",
        "> 由 GitHub Actions 自动生成 · 数据来源：HackerNews / GitHub Trending",
        "",
        "---",
        "",
    ]

    for i, (post, img_path) in enumerate(zip(posts, image_paths), 1):
        line1 = post.get("cover_line1", "")
        line2 = post.get("cover_line2", "")
        parts.append(f"## 帖子 {i} · {post.get('topic', '')}")
        parts.append("")

        # 封面标题
        parts += ["**📌 封面标题：**", "```", f"{line1}", f"{line2}", "```", ""]

        # 封面图
        if img_path and GITHUB_REPO:
            raw_url = (
                f"https://raw.githubusercontent.com/{GITHUB_REPO}/{branch}/{img_path}"
            )
            parts += [f"**🖼️ 封面图：**", f"![cover{i}]({raw_url})", ""]

        # 正文
        parts += ["**📝 正文：**", "", post.get("body", ""), ""]

        # 话题标签
        tags    = post.get("tags", [])
        tag_str = "  ".join(f"`#{t}`" for t in tags)
        parts  += [f"**🏷️ 话题标签：** {tag_str}", "", "---", ""]

    parts += [
        f"<sub>✨ Generated by [ai-xiaohongshu-daily]"
        f"(https://github.com/{GITHUB_REPO or 'your/repo'})</sub>",
    ]
    return "\n".join(parts)


def create_github_issue(
    posts: list[dict], image_paths: list[str | None]
) -> str | None:
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("  ⚠️  GITHUB_TOKEN / GITHUB_REPOSITORY not set, skipping")
        return None

    owner, repo = GITHUB_REPO.split("/", 1)
    _ensure_labels(owner, repo)
    branch = get_default_branch(owner, repo)
    print(f"  🌿 Default branch: {branch}")

    body    = build_issue_body(posts, image_paths, branch=branch)
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github.v3+json",
    }

    print("📝 Creating GitHub Issue…")
    try:
        resp = requests.post(
            f"https://api.github.com/repos/{owner}/{repo}/issues",
            headers=headers,
            json={
                "title":  f"📱 AI 日报 · {TODAY}",
                "body":   body,
                "labels": ["daily-post", "ai-content"],
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
# 5. 飞书通知
# ══════════════════════════════════════════════════════════════════════════════

def send_feishu_notify(posts: list[dict]) -> None:
    """将每篇帖子作为独立飞书消息发出，方便逐条复制。"""
    if not FEISHU_WEBHOOK:
        print("  ⚠️  FEISHU_WEBHOOK not set, skipping Feishu notification")
        return

    print("📨 Sending Feishu notifications…")
    for i, post in enumerate(posts, 1):
        topic   = post.get("topic", f"帖子{i}")
        line1   = post.get("cover_line1", "")
        line2   = post.get("cover_line2", "")
        body    = post.get("body", "")
        tags    = post.get("tags", [])
        tag_str = " ".join(f"#{t}" for t in tags)

        # 纯文本格式，易于手动复制
        text = (
            f"📱 AI日报 {TODAY_CN} · 帖子{i}/{len(posts)} · {topic}\n"
            f"{'─' * 36}\n"
            f"🎨 封面标题\n"
            f"{line1}\n"
            f"{line2}\n\n"
            f"📝 正文\n"
            f"{body}\n\n"
            f"🏷️ 标签\n"
            f"{tag_str}"
        )

        try:
            resp = requests.post(
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


def phase_notify() -> None:
    print(f"\n🚀 Phase 3: Feishu Notify  [{TODAY}]\n{'─'*50}")

    if not DATA_FILE.exists():
        print("❌ posts_data.json not found. Run --phase generate first.")
        sys.exit(1)

    data  = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    posts = data["posts"]
    send_feishu_notify(posts)
    print("  🎉 Feishu notify done")


# ══════════════════════════════════════════════════════════════════════════════
# 6. 主流程
# ══════════════════════════════════════════════════════════════════════════════

DATA_FILE = Path("posts_data.json")


def phase_generate() -> None:
    print(f"\n🚀 Phase 1: Generate  [{TODAY}]\n{'─'*50}")

    hn_stories   = fetch_hackernews_ai(limit=6)
    github_repos = fetch_github_trending_ai(limit=6)
    topics       = {"hackernews": hn_stories, "github_trending": github_repos}
    print(f"  Total: {len(hn_stories)} HN + {len(github_repos)} GitHub\n")

    posts = generate_posts_with_llm(topics)
    if not posts:
        print("❌ No posts generated. Exiting.")
        sys.exit(1)

    image_paths = generate_cover_images(posts)

    data = {"date": TODAY, "posts": posts, "image_paths": image_paths}
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n💾 Saved posts_data.json ({len(posts)} posts)")


def phase_issue() -> None:
    print(f"\n🚀 Phase 2: Create Issue  [{TODAY}]\n{'─'*50}")

    if not DATA_FILE.exists():
        print("❌ posts_data.json not found. Run --phase generate first.")
        sys.exit(1)

    data        = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    posts       = data["posts"]
    image_paths = data["image_paths"]

    issue_url = create_github_issue(posts, image_paths)
    if issue_url:
        print(f"\n🎉 Done! Issue: {issue_url}")
    else:
        print("\n❌ Issue creation failed.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 日报生成器")
    parser.add_argument(
        "--phase",
        choices=["generate", "issue", "notify", "all"],
        default="all",
        help="generate | issue | notify | all",
    )
    args = parser.parse_args()

    if args.phase in ("generate", "all"):
        phase_generate()
    if args.phase in ("issue", "all"):
        phase_issue()
    if args.phase in ("notify", "all"):
        phase_notify()


if __name__ == "__main__":
    main()
