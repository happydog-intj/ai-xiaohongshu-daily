#!/usr/bin/env python3
"""
news_digest.py — HackerNews & a16z 每日热帖 → 飞书简单卡片推送

流程：
    1. 抓取 HN Top N + a16z Latest N
    2. 用 LLM 翻译标题 + 生成中文摘要（批量，一次调用）
    3. 用 card_generator.generate_news_card() 渲染 PNG
    4. 通过飞书 App API（FEISHU_APP_ID/SECRET + FEISHU_USER_ID）
       逐条发送图片消息 + 附带原文链接的文本消息

环境变量（与 generate_post.py 共用）：
    LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
    FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_USER_ID
    FEISHU_WEBHOOK（可选，降级用）

用法：
    python scripts/news_digest.py                     # 两源各取5条
    python scripts/news_digest.py --hn 8 --a16z 5
    python scripts/news_digest.py --no-card --no-img  # 纯文字模式
    python scripts/news_digest.py --dry-run           # 本地调试，不发飞书
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ── 路径设置 ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from fetch_news import fetch_hackernews, fetch_a16z  # noqa: E402
from card_generator import generate_news_card          # noqa: E402

# ── 常量 ─────────────────────────────────────────────────────────────────────
CST      = timezone(timedelta(hours=8))
NOW      = datetime.now(CST)
TODAY    = NOW.strftime("%Y-%m-%d")
TODAY_CN = NOW.strftime("%Y年%m月%d日")
HOUR_STR = NOW.strftime("%H:%M")

ASSETS_DIR = Path("assets") / TODAY / "news"

# ── 环境变量 ─────────────────────────────────────────────────────────────────
LLM_API_KEY        = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL       = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_MODEL          = os.environ.get("LLM_MODEL", "gpt-4o-mini")
FEISHU_WEBHOOK     = os.environ.get("FEISHU_WEBHOOK", "")
FEISHU_APP_ID      = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET  = os.environ.get("FEISHU_APP_SECRET", "")
FEISHU_USER_ID     = os.environ.get("FEISHU_USER_ID", "")


# ══════════════════════════════════════════════════════════════════════════════
# LLM 翻译 & 摘要
# ══════════════════════════════════════════════════════════════════════════════

def _llm_call(messages: list[dict], max_tokens: int = 2000) -> str:
    """通用 OpenAI-兼容 LLM 调用，返回文本，失败返回空串。"""
    if not LLM_API_KEY:
        print("[LLM] No API key, skipping")
        return ""
    try:
        resp = requests.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
            json={"model": LLM_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": 0.3},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[LLM] Error: {e}")
        return ""


def translate_and_summarize(items: list[dict]) -> list[dict]:
    """
    批量翻译标题 + 生成中文摘要。
    返回每个 item 补充了 title_zh 和 summary_zh 字段的列表。
    """
    if not items:
        return items

    # 构建批量请求 payload
    payload_lines = []
    for i, item in enumerate(items):
        payload_lines.append(
            f'[{i}] 来源={item["source"]} | 标题={item["title"]} | '
            f'正文摘要={item.get("summary", "")[:600]}'
        )
    payload = "\n\n".join(payload_lines)

    prompt = f"""你是一个中英双语编辑。我给你 {len(items)} 篇文章，每篇格式：
[序号] 来源=... | 标题=... | 正文摘要=...

请为每篇返回 JSON 数组，每个元素包含：
- "idx": 序号（整数）
- "title_zh": 中文标题翻译（≤20字，直白，不加emoji）
- "summary_zh": 中文摘要（80-120字，口语化，说清楚这篇文章在讲什么、为什么值得读）

只输出 JSON 数组，不要其他文字。

文章列表：
{payload}"""

    raw = _llm_call([{"role": "user", "content": prompt}], max_tokens=3000)

    # 解析 JSON
    try:
        # 处理 LLM 可能包裹的 markdown 代码块
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        translations = json.loads(raw)
        trans_map = {int(t["idx"]): t for t in translations}
    except Exception as e:
        print(f"[LLM] JSON parse error: {e}\nRaw: {raw[:300]}")
        trans_map = {}

    for i, item in enumerate(items):
        t = trans_map.get(i, {})
        item["title_zh"]   = t.get("title_zh", item["title"])
        item["summary_zh"] = t.get("summary_zh", item.get("summary", "")[:150])

    return items


# ══════════════════════════════════════════════════════════════════════════════
# 飞书发送
# ══════════════════════════════════════════════════════════════════════════════

def _get_feishu_token() -> str:
    """获取飞书 tenant_access_token。"""
    try:
        resp = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("tenant_access_token", "")
    except Exception as e:
        print(f"[Feishu] token error: {e}")
        return ""


def _feishu_upload_image(token: str, image_path: Path) -> str:
    """上传图片到飞书，返回 image_key。"""
    try:
        with open(image_path, "rb") as f:
            resp = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/images",
                headers={"Authorization": f"Bearer {token}"},
                data={"image_type": "message"},
                files={"image": (image_path.name, f, "image/png")},
                timeout=30,
            )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 0:
            return data["data"]["image_key"]
        print(f"[Feishu] upload failed: {data}")
        return ""
    except Exception as e:
        print(f"[Feishu] upload error: {e}")
        return ""


def _feishu_send_message(token: str, msg_type: str, content: dict) -> bool:
    """发送飞书消息到 FEISHU_USER_ID（私信）。"""
    try:
        resp = requests.post(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=user_id",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "receive_id": FEISHU_USER_ID,
                "msg_type":   msg_type,
                "content":    json.dumps(content),
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("code") == 0
    except Exception as e:
        print(f"[Feishu] send error: {e}")
        return False


def _feishu_webhook_send(text: str) -> bool:
    """降级：发送纯文字到飞书 Webhook。"""
    if not FEISHU_WEBHOOK:
        return False
    try:
        resp = requests.post(
            FEISHU_WEBHOOK,
            json={"msg_type": "text", "content": {"text": text}},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("code") == 0
    except Exception as e:
        print(f"[Feishu/webhook] error: {e}")
        return False


def send_item_to_feishu(
    item: dict,
    img_path: Path | None,
    dry_run: bool = False,
) -> None:
    """向飞书发送单条新闻（图片卡片 + 链接文字）。"""
    title_zh   = item.get("title_zh", item["title"])
    title_en   = item["title"]
    url        = item["url"]
    source     = item["source"]
    summary_zh = item.get("summary_zh", "")

    # 纯文字消息（总是发，作为可点击链接的载体）
    text = (
        f"📌 [{source}] {title_zh}\n"
        f"▸ {title_en}\n"
        f"\n{summary_zh[:120]}\n"
        f"\n🔗 {url}"
    )

    if dry_run:
        print(f"\n{'─'*60}")
        print(f"[DRY-RUN] 飞书消息预览：")
        print(text)
        if img_path and img_path.exists():
            print(f"[DRY-RUN] 附图：{img_path}")
        return

    # 尝试 App API（有图片）
    if FEISHU_APP_ID and FEISHU_APP_SECRET and FEISHU_USER_ID:
        token = _get_feishu_token()
        if token:
            # 先发图片
            if img_path and img_path.exists():
                image_key = _feishu_upload_image(token, img_path)
                if image_key:
                    _feishu_send_message(token, "image", {"image_key": image_key})
                    time.sleep(0.5)

            # 再发文字（含链接）
            ok = _feishu_send_message(token, "text", {"text": text})
            if ok:
                print(f"[Feishu] ✓ 发送成功: {title_zh[:30]}")
                return

    # 降级：Webhook 纯文字
    if FEISHU_WEBHOOK:
        _feishu_webhook_send(text)
        print(f"[Feishu/webhook] ✓ 发送: {title_zh[:30]}")
        return

    print(f"[Feishu] ⚠ 无可用发送方式，跳过: {title_zh[:30]}")


# ══════════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════════

def send_digest_header(dry_run: bool = False, hn_n: int = 5, a16z_n: int = 5) -> None:
    """发送日报头部汇总消息。"""
    text = (
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📰 HN & a16z 日报 · {TODAY_CN} {HOUR_STR}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"即将推送 HackerNews Top {hn_n} + a16z Latest {a16z_n}\n"
        f"每条卡片含：原文标题 · 中文翻译 · 摘要 · 原文链接"
    )
    if dry_run:
        print("\n" + text)
        return
    if FEISHU_APP_ID and FEISHU_APP_SECRET and FEISHU_USER_ID:
        token = _get_feishu_token()
        if token:
            _feishu_send_message(token, "text", {"text": text})
            return
    if FEISHU_WEBHOOK:
        _feishu_webhook_send(text)


def run(hn_n: int = 5, a16z_n: int = 5, no_card: bool = False, dry_run: bool = False) -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. 抓取 ────────────────────────────────────────────────────────────
    print(f"\n[1/4] 抓取 HackerNews Top {hn_n}...")
    hn_items = fetch_hackernews(top_n=hn_n)

    print(f"\n[1/4] 抓取 a16z Latest {a16z_n}...")
    a16z_items = fetch_a16z(top_n=a16z_n)

    all_items = hn_items + a16z_items
    print(f"      共获取 {len(all_items)} 条（HN: {len(hn_items)}, a16z: {len(a16z_items)}）")

    if not all_items:
        print("[!] 没有抓到任何内容，退出")
        return

    # ── 2. LLM 翻译 ────────────────────────────────────────────────────────
    print(f"\n[2/4] LLM 批量翻译 & 摘要（{len(all_items)} 条）...")
    all_items = translate_and_summarize(all_items)

    # ── 3. 生成卡片图片 ────────────────────────────────────────────────────
    print(f"\n[3/4] 生成卡片图片...")
    for i, item in enumerate(all_items):
        if no_card:
            item["_img_path"] = None
            continue
        img_path = ASSETS_DIR / f"{item['source'].lower()}_{i+1:02d}.png"
        ok = generate_news_card(item, img_path, date_str=f"{TODAY} {HOUR_STR}")
        item["_img_path"] = img_path if ok else None
        status = "✓" if ok else "✗"
        print(f"  {status} {img_path.name}")

    # ── 4. 发送飞书 ────────────────────────────────────────────────────────
    print(f"\n[4/4] 发送飞书...")
    send_digest_header(dry_run=dry_run, hn_n=len(hn_items), a16z_n=len(a16z_items))
    time.sleep(1)

    for item in all_items:
        send_item_to_feishu(item, item.get("_img_path"), dry_run=dry_run)
        time.sleep(1.5)   # 避免飞书限流

    print(f"\n✅ 完成！共推送 {len(all_items)} 条")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HN & a16z 日报 → 飞书卡片")
    parser.add_argument("--hn",       type=int,  default=5,     help="HackerNews 条数（默认5）")
    parser.add_argument("--a16z",     type=int,  default=5,     help="a16z 条数（默认5）")
    parser.add_argument("--no-card",  action="store_true",      help="跳过卡片图片生成（纯文字）")
    parser.add_argument("--dry-run",  action="store_true",      help="本地预览，不发飞书")
    args = parser.parse_args()

    run(
        hn_n=args.hn,
        a16z_n=args.a16z,
        no_card=args.no_card,
        dry_run=args.dry_run,
    )
