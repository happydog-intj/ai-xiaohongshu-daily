#!/usr/bin/env python3
"""
fetch_news.py — HackerNews & a16z 热帖抓取模块

对外暴露两个函数：
    fetch_hackernews(top_n=10)  → List[dict]
    fetch_a16z(top_n=10)        → List[dict]

每个 dict 结构：
    {
        "source":  "HackerNews" | "a16z",
        "title":   str,         # 原文标题
        "url":     str,         # 文章链接
        "points":  int | None,  # HN 分数 / a16z 无此字段则 None
        "comments":int | None,  # HN 评论数 / a16z 无则 None
        "summary": str,         # 正文摘要（前 800 字，供 LLM 翻译使用）
    }
"""

import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ── HTTP 工具 ────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _get(url: str, timeout: int = 15) -> Optional[requests.Response]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp
    except Exception as e:
        print(f"[fetch_news] GET failed: {url} — {e}")
        return None


def _extract_text(url: str, max_chars: int = 1000) -> str:
    """抓取文章正文，截取前 max_chars 字符作为摘要。失败返回空串。"""
    resp = _get(url, timeout=20)
    if not resp:
        return ""
    try:
        soup = BeautifulSoup(resp.text, "lxml")
        # 移除 script / style / nav / footer
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        # 优先取 article / main，否则取 body
        container = soup.find("article") or soup.find("main") or soup.body
        if not container:
            return ""
        text = re.sub(r"\s+", " ", container.get_text(" ", strip=True))
        return text[:max_chars].strip()
    except Exception:
        return ""


# ── HackerNews ───────────────────────────────────────────────────────────────

HN_API_TOP  = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_API_ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"


def fetch_hackernews(top_n: int = 10) -> list[dict]:
    """
    抓取 HackerNews 当前 Top N 帖子（含正文摘要）。
    跳过 Ask HN / Show HN / 纯讨论帖（无 url 字段的条目）。
    """
    resp = _get(HN_API_TOP)
    if not resp:
        return []

    ids = resp.json()[:60]  # 取前 60 条，过滤后取 top_n
    results = []

    for item_id in ids:
        if len(results) >= top_n:
            break
        item_resp = _get(HN_API_ITEM.format(id=item_id))
        if not item_resp:
            continue
        item = item_resp.json()

        # 跳过无外链条目（Ask HN、Jobs 等）
        url = item.get("url", "")
        if not url:
            continue

        title   = item.get("title", "").strip()
        points  = item.get("score", 0)
        comments = item.get("descendants", 0)

        # 抓正文摘要（短暂延迟避免被封）
        summary = _extract_text(url, max_chars=1000)
        time.sleep(0.3)

        results.append({
            "source":   "HackerNews",
            "title":    title,
            "url":      url,
            "points":   points,
            "comments": comments,
            "summary":  summary,
        })
        print(f"[HN] #{len(results):02d} {title[:60]}")

    return results


# ── a16z ─────────────────────────────────────────────────────────────────────

A16Z_BLOG_URL = "https://a16z.com/feed/"           # RSS feed（最稳定）
A16Z_SITE_URL = "https://a16z.com/posts/"          # 备用：HTML 文章列表页


def _fetch_a16z_rss(top_n: int) -> list[dict]:
    """优先通过 RSS 抓取 a16z 最新文章。"""
    resp = _get(A16Z_BLOG_URL)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "lxml-xml")
    items = soup.find_all("item")
    results = []

    for item in items[:top_n * 2]:  # 多取一些备用
        if len(results) >= top_n:
            break
        title = item.find("title")
        link  = item.find("link")
        if not title or not link:
            continue

        title_text = title.get_text(strip=True)
        url        = link.get_text(strip=True) or (link.next_sibling or "").strip()

        # RSS link 标签有时是空文本，内容在 CDATA 或 next_sibling
        if not url:
            url = str(link.next_sibling or "").strip()
        if not url or not url.startswith("http"):
            continue

        summary = _extract_text(url, max_chars=1000)
        time.sleep(0.3)

        results.append({
            "source":   "a16z",
            "title":    title_text,
            "url":      url,
            "points":   None,
            "comments": None,
            "summary":  summary,
        })
        print(f"[a16z] #{len(results):02d} {title_text[:60]}")

    return results


def _fetch_a16z_html(top_n: int) -> list[dict]:
    """RSS 失败时备用：直接抓 a16z.com/posts 页面。"""
    resp = _get(A16Z_SITE_URL)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    results = []

    # a16z 文章列表：<a> 标签含 /posts/ 路径
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/posts/" not in href and "/ideas/" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)

        full_url = href if href.startswith("http") else "https://a16z.com" + href
        title = a.get_text(strip=True)
        if len(title) < 10:   # 过滤短文本（导航按钮等）
            continue

        summary = _extract_text(full_url, max_chars=1000)
        time.sleep(0.3)

        results.append({
            "source":   "a16z",
            "title":    title,
            "url":      full_url,
            "points":   None,
            "comments": None,
            "summary":  summary,
        })
        print(f"[a16z/html] #{len(results):02d} {title[:60]}")

        if len(results) >= top_n:
            break

    return results


def fetch_a16z(top_n: int = 10) -> list[dict]:
    """抓取 a16z 最新 top_n 篇文章，RSS 优先，失败时 fallback 到 HTML 抓取。"""
    results = _fetch_a16z_rss(top_n)
    if not results:
        print("[a16z] RSS failed, trying HTML fallback...")
        results = _fetch_a16z_html(top_n)
    return results[:top_n]


# ── 本地测试入口 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    print("=== HackerNews Top 5 ===")
    hn = fetch_hackernews(top_n=5)
    print(json.dumps(hn, ensure_ascii=False, indent=2)[:3000])

    print("\n=== a16z Latest 5 ===")
    a16z = fetch_a16z(top_n=5)
    print(json.dumps(a16z, ensure_ascii=False, indent=2)[:3000])
