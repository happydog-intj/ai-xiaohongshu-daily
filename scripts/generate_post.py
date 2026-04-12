#!/usr/bin/env python3
"""
AI 小红书日报生成器
每天自动抓取 AI 热点，生成小红书风格内容 + Qwen 封面图，发布为 GitHub Issue
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

# ── 时区 & 常量 ────────────────────────────────────────────────────────────────
CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).strftime("%Y-%m-%d")
TODAY_CN = datetime.now(CST).strftime("%Y年%m月%d日")

ASSETS_DIR = Path("assets") / TODAY

AI_KEYWORDS = {
    "ai", "llm", "gpt", "claude", "gemini", "agent", "openai",
    "anthropic", "deepmind", "mistral", "llama", "model", "neural",
    "diffusion", "transformer", "rag", "fine-tun",
}

# ── 环境变量 ────────────────────────────────────────────────────────────────────
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
LLM_API_KEY       = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL      = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_MODEL         = os.environ.get("LLM_MODEL", "gpt-4o-mini")
GITHUB_TOKEN      = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO       = os.environ.get("GITHUB_REPOSITORY", "")   # owner/repo


# ══════════════════════════════════════════════════════════════════════════════
# 1. 数据抓取
# ══════════════════════════════════════════════════════════════════════════════

def fetch_hackernews_ai(limit: int = 6) -> list[dict]:
    """从 HackerNews Top Stories 过滤 AI 相关帖子"""
    print("📡 Fetching HackerNews…")
    try:
        ids = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=10,
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
                f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                timeout=6,
            ).json()
            title = (item.get("title") or "").lower()
            if any(kw in title for kw in AI_KEYWORDS):
                stories.append({
                    "source": "HackerNews",
                    "title": item.get("title", ""),
                    "url":   item.get("url", ""),
                    "score": item.get("score", 0),
                })
        except Exception:
            pass

    print(f"  ✅ {len(stories)} HN stories")
    return stories


def fetch_github_trending_ai(limit: int = 6) -> list[dict]:
    """GitHub 搜索近 7 天创建、Stars 最多的 AI 相关项目"""
    print("📡 Fetching GitHub Trending…")
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        resp = requests.get(
            "https://api.github.com/search/repositories",
            params={
                "q": f"topic:ai OR topic:llm created:>{week_ago}",
                "sort": "stars",
                "order": "desc",
                "per_page": limit,
            },
            headers=headers,
            timeout=12,
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
# 2. LLM 生成内容
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是小红书顶级 AI 科技博主「AI炼丹师」。
你的帖子特点：
- 标题：震惊体、口语化、2行（用\\n分隔），含数字或感叹词
- 正文：干货满满、emoji 点缀、短段落（每段2-4行）、步骤清晰、结尾有互动引导
- 语言：中文为主，技术术语保留英文
- 风格：接地气、有观点、不过分正式
"""

USER_PROMPT_TEMPLATE = """今天是{today}，以下是今日 AI 圈最热话题和项目（JSON 格式）：

{topics}

请从中挑选最有价值的 **4 个**话题（优先选新颖、有实用价值、能引发讨论的），
为每个话题生成一篇小红书帖子。

输出必须是合法 JSON 数组（不要包含其他文字），格式如下：
[
  {{
    "topic": "话题简短名称（10字以内）",
    "cover_title": "封面标题第一行\\n封面标题第二行",
    "cover_image_prompt": "English prompt for Wanx image generation. Dark cyberpunk style, AI tech blog cover, no text in image.",
    "body": "正文（含emoji、分段、互动引导）",
    "tags": ["标签1", "标签2", "标签3", "标签4", "标签5", "标签6", "标签7", "标签8", "标签9", "标签10"]
  }}
]
"""


def generate_posts_with_llm(topics: dict) -> list[dict]:
    """调用 LLM 生成 4 篇小红书帖子"""
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
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                "temperature": 0.85,
                "max_tokens":  4096,
            },
            timeout=90,
        )
        raw = resp.json()["choices"][0]["message"]["content"].strip()

        # 提取 JSON 数组（防止 LLM 在前后加说明文字）
        start = raw.find("[")
        end   = raw.rfind("]") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

        posts = json.loads(raw)
        print(f"  ✅ {len(posts)} posts generated")
        return posts[:4]
    except Exception as e:
        print(f"  ⚠️  LLM generation failed: {e}")
        return _fallback_posts(topics)


def _fallback_posts(topics: dict) -> list[dict]:
    """LLM 不可用时的兜底模板"""
    items = topics.get("hackernews", []) + topics.get("github_trending", [])
    posts = []
    for item in items[:4]:
        title = item.get("title") or item.get("name", "AI 热点")
        desc  = item.get("description", "")
        url   = item.get("url", "")
        posts.append({
            "topic": title[:20],
            "cover_title": f"今日 AI 热点\n{title[:20]}",
            "cover_image_prompt": (
                "dark cyberpunk AI tech illustration, purple blue neon lights, "
                "circuit board, neural network, no text"
            ),
            "body": (
                f"🔥 今日热点来了！\n\n"
                f"**{title}**\n\n"
                f"{desc}\n\n"
                f"🔗 详情：{url}\n\n"
                f"关注我，每天第一时间 AI 动态！👇"
            ),
            "tags": ["AI", "人工智能", "大模型", "科技", "每日热点",
                     "机器学习", "深度学习", "AI工具", "技术", "炼丹"],
        })
    return posts


# ══════════════════════════════════════════════════════════════════════════════
# 3. DashScope Wanx 图像生成
# ══════════════════════════════════════════════════════════════════════════════

DASHSCOPE_SUBMIT = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
    "text2image/image-synthesis"
)
DASHSCOPE_POLL = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"


def _ds_headers() -> dict:
    return {
        "Authorization":    f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type":     "application/json",
        "X-DashScope-Async": "enable",
    }


def submit_image_task(prompt: str) -> str | None:
    try:
        resp = requests.post(
            DASHSCOPE_SUBMIT,
            headers=_ds_headers(),
            json={
                "model": "wanx2.1-t2i-turbo",
                "input": {"prompt": prompt},
                "parameters": {"size": "1024*1024", "n": 1},
            },
            timeout=30,
        )
        task_id = resp.json()["output"]["task_id"]
        print(f"    🎨 Submitted task: {task_id}")
        return task_id
    except Exception as e:
        print(f"    ⚠️  Submit failed: {e}")
        return None


def poll_image_task(task_id: str, max_wait: int = 120) -> str | None:
    """轮询任务直到完成，返回图片 URL"""
    for _ in range(max_wait // 5):
        time.sleep(5)
        try:
            resp = requests.get(
                DASHSCOPE_POLL.format(task_id=task_id),
                headers={"Authorization": f"Bearer {DASHSCOPE_API_KEY}"},
                timeout=15,
            )
            out = resp.json().get("output", {})
            status = out.get("task_status")
            if status == "SUCCEEDED":
                return out["results"][0]["url"]
            elif status == "FAILED":
                print(f"    ❌ Task failed: {out.get('message', '')}")
                return None
        except Exception as e:
            print(f"    ⚠️  Poll error: {e}")
    print(f"    ⏱️  Task {task_id} timed out")
    return None


def generate_cover_images(posts: list[dict]) -> list[str | None]:
    """并发提交所有图片任务，依次等待结果"""
    if not DASHSCOPE_API_KEY:
        print("  ⚠️  DASHSCOPE_API_KEY not set, skipping image generation")
        return [None] * len(posts)

    print("🎨 Generating cover images…")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # 并发提交
    task_ids = [submit_image_task(p.get("cover_image_prompt", "")) for p in posts]

    # 依次等待 & 下载
    image_paths: list[str | None] = []
    for i, (tid, post) in enumerate(zip(task_ids, posts), 1):
        if not tid:
            image_paths.append(None)
            continue
        url = poll_image_task(tid)
        if url:
            dest = ASSETS_DIR / f"cover{i}.png"
            try:
                r = requests.get(url, timeout=30)
                dest.write_bytes(r.content)
                print(f"    ✅ Downloaded cover{i}.png ({len(r.content)//1024} KB)")
                image_paths.append(str(dest))
            except Exception as e:
                print(f"    ⚠️  Download failed: {e}")
                image_paths.append(None)
        else:
            image_paths.append(None)

    return image_paths


# ══════════════════════════════════════════════════════════════════════════════
# 4. GitHub Issue 创建
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_labels(owner: str, repo: str) -> None:
    """确保 daily-post 和 ai-content label 存在"""
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
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
            pass  # 已存在会返回 422，忽略即可


def build_issue_body(posts: list[dict], image_paths: list[str | None]) -> str:
    parts = [
        f"# 🤖 AI 小红书日报 · {TODAY_CN}",
        "",
        "> 由 GitHub Actions 自动生成 · 数据来源：HackerNews / GitHub Trending",
        "",
        "---",
        "",
    ]

    for i, (post, img_path) in enumerate(zip(posts, image_paths), 1):
        parts.append(f"## 帖子 {i} · {post.get('topic', '')}")
        parts.append("")

        # 封面标题
        cover_title = post.get("cover_title", "").replace("\\n", "\n")
        parts += ["**📌 封面标题：**", "```", cover_title, "```", ""]

        # 封面图（raw GitHub URL）
        if img_path and GITHUB_REPO:
            raw_url = (
                f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{img_path}"
            )
            parts += [f"**🖼️ 封面图：**", f"![cover{i}]({raw_url})", ""]

        # 正文
        parts += ["**📝 正文：**", "", post.get("body", ""), ""]

        # 话题标签
        tags = post.get("tags", [])
        tag_str = "  ".join(f"`#{t}`" for t in tags)
        parts += [f"**🏷️ 话题标签：** {tag_str}", "", "---", ""]

    parts += [
        "<sub>✨ Generated by [ai-xiaohongshu-daily](https://github.com/"
        + (GITHUB_REPO or "your/repo")
        + ")</sub>",
    ]
    return "\n".join(parts)


def create_github_issue(posts: list[dict], image_paths: list[str | None]) -> str | None:
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("  ⚠️  GITHUB_TOKEN / GITHUB_REPOSITORY not set, skipping")
        return None

    owner, repo = GITHUB_REPO.split("/", 1)
    _ensure_labels(owner, repo)

    body = build_issue_body(posts, image_paths)
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    print("📝 Creating GitHub Issue…")
    try:
        resp = requests.post(
            f"https://api.github.com/repos/{owner}/{repo}/issues",
            headers=headers,
            json={
                "title":  f"📱 AI 小红书日报 · {TODAY}",
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
# 5. 主流程
# ══════════════════════════════════════════════════════════════════════════════

DATA_FILE = Path("posts_data.json")


def phase_generate() -> None:
    """阶段 1：抓数据 → 生成内容 → 生成图片 → 保存 posts_data.json"""
    print(f"\n🚀 Phase 1: Generate  [{TODAY}]\n{'─'*50}")

    # 抓数据
    hn_stories   = fetch_hackernews_ai(limit=6)
    github_repos = fetch_github_trending_ai(limit=6)
    topics = {"hackernews": hn_stories, "github_trending": github_repos}
    print(f"  Total topics: {len(hn_stories)} HN + {len(github_repos)} GitHub\n")

    # 生成内容
    posts = generate_posts_with_llm(topics)
    if not posts:
        print("❌ No posts generated. Exiting.")
        sys.exit(1)

    # 生成图片
    image_paths = generate_cover_images(posts)

    # 保存数据供 phase issue 使用
    data = {
        "date":         TODAY,
        "posts":        posts,
        "image_paths":  image_paths,
    }
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n💾 Saved posts_data.json ({len(posts)} posts)")


def phase_issue() -> None:
    """阶段 2：读取 posts_data.json → 创建 GitHub Issue"""
    print(f"\n🚀 Phase 2: Create Issue  [{TODAY}]\n{'─'*50}")

    if not DATA_FILE.exists():
        print("❌ posts_data.json not found. Run --phase generate first.")
        sys.exit(1)

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    posts       = data["posts"]
    image_paths = data["image_paths"]

    issue_url = create_github_issue(posts, image_paths)
    if issue_url:
        print(f"\n🎉 Done! Issue: {issue_url}")
    else:
        print("\n❌ Issue creation failed.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 小红书日报生成器")
    parser.add_argument(
        "--phase",
        choices=["generate", "issue", "all"],
        default="all",
        help="generate: 生成内容+图片  |  issue: 创建 GitHub Issue  |  all: 两步都做",
    )
    args = parser.parse_args()

    if args.phase in ("generate", "all"):
        phase_generate()
    if args.phase in ("issue", "all"):
        phase_issue()


if __name__ == "__main__":
    main()
