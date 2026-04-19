#!/usr/bin/env python3
"""
GitHub Trending AI 追踪器
每天 08:00 / 21:00（北京时间）抓取 GitHub Trending 当日 Top 10，
筛选 AI 相关项目，用 LLM 生成小红书风格 Issue，并可选发飞书通知。
"""

import argparse
import json
import os
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


def build_issue_body(posts: list[dict], all_repos: list[dict], ai_repos: list[dict]) -> str:
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

    # 精选帖子详情
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
    posts: list[dict], all_repos: list[dict], ai_repos: list[dict]
) -> str | None:
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("  ⚠️  GITHUB_TOKEN / GITHUB_REPOSITORY not set, skipping")
        return None

    owner, repo = GITHUB_REPO.split("/", 1)
    _ensure_labels(owner, repo)

    body    = build_issue_body(posts, all_repos, ai_repos)
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
# 5. 主流程
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="GitHub Trending AI 追踪器")
    parser.add_argument("--since",     default="daily",  choices=["daily", "weekly", "monthly"])
    parser.add_argument("--top-n",     default=10,  type=int, help="抓取 Trending 条数")
    parser.add_argument("--max-posts", default=4,   type=int, help="最多生成帖子数")
    parser.add_argument("--no-issue",  action="store_true",   help="跳过创建 Issue")
    parser.add_argument("--no-notify", action="store_true",   help="跳过飞书通知")
    args = parser.parse_args()

    print(f"\n🚀 GitHub Trending AI {SLOT}  [{TODAY} {HOUR}:xx]\n{'─'*54}")

    # 1. 抓取 Trending
    all_repos = fetch_github_trending(since=args.since, top_n=args.top_n)
    if not all_repos:
        print("❌ No repos fetched. Exiting.")
        sys.exit(1)

    # 2. 过滤 AI 项目
    ai_repos = filter_ai_repos(all_repos)
    if not ai_repos:
        print("ℹ️  No AI repos found in today's Trending. Creating placeholder issue.")
        ai_repos = all_repos[:3]   # 保底取前 3 个

    # 3. LLM 生成小红书帖子
    posts = generate_posts_with_llm(ai_repos, max_posts=args.max_posts)
    if not posts:
        print("❌ No posts generated. Exiting.")
        sys.exit(1)

    # 4. 保存中间数据
    DATA_FILE.write_text(
        json.dumps(
            {"date": TODAY, "slot": SLOT, "all_repos": all_repos,
             "ai_repos": ai_repos, "posts": posts},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"💾 Saved {DATA_FILE}")

    # 5. 创建 GitHub Issue
    issue_url = None
    if not args.no_issue:
        issue_url = create_github_issue(posts, all_repos, ai_repos)

    # 6. 飞书通知
    if not args.no_notify:
        send_feishu_notify(posts, issue_url)

    print(f"\n🎉 Done! {SLOT} {TODAY}  {len(posts)} posts")


if __name__ == "__main__":
    main()
