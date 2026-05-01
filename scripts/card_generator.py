#!/usr/bin/env python3
"""
card_generator.py
共享的卡片生成模块。使用 Playwright 将 HTML 渲染为 PNG。
设计风格来源：ljg-card skill（长图模具），footer 仅保留「AI日报」来源标注。
"""

import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# ── 路径 ────────────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).parent.parent
CAPTURE_JS  = REPO_ROOT / "tools" / "card" / "capture.js"

# ── 色彩主题 ─────────────────────────────────────────────────────────────────
# 技术/AI 内容 → 蓝灰系
THEME_TECH = {"bg": "#F5F7FA", "accent": "#3D5A80"}
# 热榜/热点内容 → 暖红系
THEME_WARM = {"bg": "#FAF7F5", "accent": "#8B3A3A"}


# ══════════════════════════════════════════════════════════════════════════════
# HTML 模板（基于 ljg-card long_template，footer 无作者）
# ══════════════════════════════════════════════════════════════════════════════

_CARD_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;500;600;700&display=swap');

  :root {{
    --bg:       {bg};
    --text:     #1D1D1F;
    --text-mid: #6E6E73;
    --text-dim: #ACACB0;
    --accent:   {accent};
    --rule:     #E5E5EA;
    --font:     'KingHwa_OldSong', 'Noto Serif SC', 'PingFang SC', 'STSong', Georgia, serif;
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  html, body {{
    width: 1080px;
    background: var(--bg);
  }}

  .card {{
    width: 1080px;
    background: var(--bg);
    padding: 64px 72px 52px;
    display: flex;
    flex-direction: column;
  }}

  /* ── Title ── */
  .title-area {{
    flex-shrink: 0;
    margin-bottom: 52px;
  }}

  .title-area .eyebrow {{
    font: 400 20px/2 var(--font);
    color: var(--text-dim);
    letter-spacing: 0.15em;
    margin-bottom: 10px;
  }}

  .title-area h1 {{
    font: 700 80px/1.15 var(--font);
    color: var(--text);
    letter-spacing: -0.03em;
    margin-bottom: 16px;
  }}

  .title-area .tagline {{
    font: 400 38px/1.5 var(--font);
    color: var(--accent);
    letter-spacing: -0.01em;
    margin-bottom: 22px;
  }}

  .title-area::after {{
    content: '';
    display: block;
    width: 52px;
    height: 3px;
    background: var(--accent);
  }}

  /* ── Content ── */
  .content {{
    display: flex;
    flex-direction: column;
  }}

  .content p {{
    font: 400 34px/1.75 var(--font);
    color: var(--text);
    margin-bottom: 26px;
  }}

  .content .dropcap::first-letter {{
    font: 700 120px/0.82 var(--font);
    float: left;
    margin: 4px 14px 0 -4px;
    color: var(--accent);
  }}

  .content .highlight {{
    font: 500 38px/1.55 var(--font);
    color: var(--text);
    padding: 14px 0 14px 26px;
    border-left: 3px solid var(--accent);
    margin: 36px 0;
  }}

  .content h2 {{
    font: 600 40px/1.4 var(--font);
    color: var(--text);
    margin: 40px 0 18px;
    letter-spacing: -0.02em;
  }}

  .content .item {{
    margin-bottom: 32px;
    padding: 24px 28px;
    background: rgba(61,90,128,0.05);
    border-radius: 10px;
    border-left: 3px solid var(--accent);
  }}

  .content .item .label {{
    font: 600 30px/1.5 var(--font);
    color: var(--accent);
    margin-bottom: 8px;
  }}

  .content .item p {{
    font: 400 28px/1.65 var(--font);
    color: var(--text-mid);
    margin-bottom: 0;
  }}

  .content blockquote {{
    margin: 0 0 26px;
    padding-left: 26px;
    border-left: 3px solid var(--rule);
  }}

  .content blockquote p {{
    font: 300 34px/1.7 var(--font);
    color: var(--text-mid);
    margin-bottom: 4px;
  }}

  .content strong {{
    font-weight: 600;
    color: var(--text);
  }}

  .content .divider {{
    height: 1px;
    background: var(--rule);
    margin: 32px 0;
  }}

  .content ul {{
    list-style: none;
    margin-bottom: 26px;
  }}

  .content ul li {{
    font: 400 34px/1.7 var(--font);
    color: var(--text);
    padding: 4px 0 4px 28px;
    position: relative;
  }}

  .content ul li::before {{
    content: '·';
    position: absolute;
    left: 0;
    color: var(--text-mid);
  }}

  /* ── Tags ── */
  .tags {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 32px;
    margin-bottom: 8px;
  }}

  .tags .tag {{
    font: 400 18px/1 'Menlo', 'SF Mono', 'Consolas', monospace;
    color: var(--accent);
    background: rgba(61,90,128,0.08);
    padding: 6px 14px;
    border-radius: 20px;
    letter-spacing: 0.02em;
  }}

  /* ── End mark ── */
  .content::after {{
    content: '∎';
    display: block;
    text-align: right;
    font-size: 16px;
    color: var(--accent);
    opacity: 0.4;
    margin-top: 36px;
  }}

  /* ── Footer ── */
  .footer {{
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    margin-top: 48px;
    padding-top: 20px;
    border-top: 1px solid var(--rule);
  }}

  .footer .source {{
    font: 400 22px/1.5 'Menlo', 'SF Mono', monospace;
    color: var(--text-dim);
    letter-spacing: 0.02em;
  }}

  /* ── Repo list (summary card) ── */
  .repo-item {{
    display: flex;
    flex-direction: column;
    padding: 18px 0;
    border-bottom: 1px solid var(--rule);
  }}

  .repo-item:last-child {{
    border-bottom: none;
  }}

  .repo-item .repo-header {{
    display: flex;
    align-items: baseline;
    gap: 14px;
    margin-bottom: 6px;
  }}

  .repo-item .repo-rank {{
    font: 700 22px/1 'Menlo', monospace;
    color: var(--accent);
    flex-shrink: 0;
    width: 36px;
  }}

  .repo-item .repo-name {{
    font: 600 32px/1.3 var(--font);
    color: var(--text);
    flex: 1;
  }}

  .repo-item .repo-meta {{
    font: 400 22px/1.5 'Menlo', monospace;
    color: var(--text-dim);
    padding-left: 50px;
  }}

  .repo-item .repo-desc {{
    font: 400 26px/1.6 var(--font);
    color: var(--text-mid);
    padding-left: 50px;
    margin-top: 4px;
  }}

  .star {{ color: #D4A017; }}
  .rise {{ color: #2D8A4E; }}
  .lang {{ color: #6B6BCC; }}
</style>
</head>
<body>
  <div class="card">
    {title_block}
    <div class="content">
      {body_html}
    </div>
    <div class="footer">
      <span class="source">AI日报</span>
    </div>
  </div>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# 内容 → HTML 转换
# ══════════════════════════════════════════════════════════════════════════════

# emoji 数字序号 → 数字字符串
_EMOJI_NUMS = {
    "1️⃣": "①", "2️⃣": "②", "3️⃣": "③",
    "4️⃣": "④", "5️⃣": "⑤", "6️⃣": "⑥",
}

def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _inline_format(text: str) -> str:
    """处理行内 **bold** 和保留 emoji。"""
    text = _escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return text


def body_to_html(body: str) -> str:
    """将帖子正文（含 emoji 序号、**bold**、段落）转为 HTML。"""
    lines = body.split("\n")
    chunks: list[str] = []
    i = 0
    first_para = True

    while i < len(lines):
        line = lines[i].rstrip()

        # 空行 → skip
        if not line.strip():
            i += 1
            continue

        # emoji 数字序号行 → item card
        matched_emoji = None
        for emoji, label in _EMOJI_NUMS.items():
            if line.startswith(emoji):
                matched_emoji = (emoji, label)
                break

        if matched_emoji:
            emoji, label = matched_emoji
            heading = line[len(emoji):].strip()
            # 收集后续非空、非另一个序号的行作为正文
            body_lines = []
            i += 1
            while i < len(lines):
                nxt = lines[i].rstrip()
                if not nxt.strip():
                    i += 1
                    break
                if any(nxt.startswith(e) for e in _EMOJI_NUMS):
                    break
                body_lines.append(nxt.strip())
                i += 1
            body_text = " ".join(body_lines)
            chunks.append(
                f'<div class="item">'
                f'<p class="label">{label} {_inline_format(heading)}</p>'
                + (f"<p>{_inline_format(body_text)}</p>" if body_text else "")
                + "</div>"
            )
            continue

        # 普通段落
        para_lines = []
        while i < len(lines) and lines[i].strip():
            if any(lines[i].startswith(e) for e in _EMOJI_NUMS):
                break
            para_lines.append(lines[i].strip())
            i += 1

        text = " ".join(para_lines)
        if not text:
            i += 1
            continue

        # 短句（≤25字，无空格分割）→ highlight 金句
        pure = re.sub(r"<[^>]+>", "", _inline_format(text))
        char_count = len(pure.replace(" ", ""))
        if char_count <= 30 and not re.search(r"[，。！？,.!?].*[，。！？,.!?]", text):
            chunks.append(f'<p class="highlight">{_inline_format(text)}</p>')
        elif first_para:
            chunks.append(f'<p class="dropcap">{_inline_format(text)}</p>')
            first_para = False
        else:
            chunks.append(f"<p>{_inline_format(text)}</p>")

    return "\n".join(chunks)


def tags_to_html(tags: list[str]) -> str:
    if not tags:
        return ""
    items = "".join(f'<span class="tag">#{_escape(t)}</span>' for t in tags)
    return f'<div class="tags">{items}</div>'


# ══════════════════════════════════════════════════════════════════════════════
# 卡片 HTML 生成
# ══════════════════════════════════════════════════════════════════════════════

def make_post_card_html(
    post: dict,
    eyebrow: str = "",
    theme: dict | None = None,
) -> str:
    """生成一篇帖子的完整卡片 HTML。"""
    t = theme or THEME_TECH

    line1 = _escape(post.get("cover_line1", post.get("topic", "")))
    line2 = _escape(post.get("cover_line2", ""))

    title_parts = []
    if eyebrow:
        title_parts.append(f'<div class="eyebrow">{_escape(eyebrow)}</div>')
    title_parts.append(f"<h1>{line1}</h1>")
    if line2:
        title_parts.append(f'<div class="tagline">{line2}</div>')
    title_block = f'<div class="title-area">{"".join(title_parts)}</div>'

    body_html = body_to_html(post.get("body", ""))
    body_html += "\n" + tags_to_html(post.get("tags", []))

    return _CARD_TEMPLATE.format(
        bg=t["bg"],
        accent=t["accent"],
        title_block=title_block,
        body_html=body_html,
    )


def make_summary_card_html(
    ai_repos: list[dict],
    slot: str = "日报",
    today_cn: str = "",
    theme: dict | None = None,
) -> str:
    """生成热榜总览卡片 HTML（trending summary）。"""
    t = theme or THEME_WARM

    eyebrow = f"GitHub Trending · {today_cn}" if today_cn else "GitHub Trending"
    title_block = (
        f'<div class="title-area">'
        f'<div class="eyebrow">{_escape(eyebrow)}</div>'
        f'<h1>今日 AI 热榜</h1>'
        f'<div class="tagline">Top {len(ai_repos)} 项目 · {_escape(slot)}</div>'
        f'</div>'
    )

    repo_html_parts = []
    for idx, repo in enumerate(ai_repos[:10], 1):
        name   = _escape(repo.get("name", ""))
        lang   = _escape(repo.get("language", ""))
        s_tot  = _escape(repo.get("stars_total", ""))
        s_day  = _escape(repo.get("stars_today", ""))
        desc   = _escape(repo.get("description", ""))

        meta_parts = []
        if lang:
            meta_parts.append(f'<span class="lang">{lang}</span>')
        if s_tot:
            meta_parts.append(f'<span class="star">★ {s_tot}</span>')
        if s_day:
            meta_parts.append(f'<span class="rise">▲ {s_day}</span>')
        meta_str = "  ·  ".join(meta_parts)

        repo_html_parts.append(
            f'<div class="repo-item">'
            f'  <div class="repo-header">'
            f'    <span class="repo-rank">{idx:02d}</span>'
            f'    <span class="repo-name">{name}</span>'
            f'  </div>'
            + (f'  <div class="repo-meta">{meta_str}</div>' if meta_str else "")
            + (f'  <div class="repo-desc">{desc}</div>' if desc else "")
            + "</div>"
        )

    body_html = "\n".join(repo_html_parts)

    return _CARD_TEMPLATE.format(
        bg=t["bg"],
        accent=t["accent"],
        title_block=title_block,
        body_html=body_html,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 截图
# ══════════════════════════════════════════════════════════════════════════════

def capture_card(html_content: str, out_path: Path, width: int = 1080) -> bool:
    """将 HTML 写入临时文件，调用 Node.js capture.js 截图，返回是否成功。"""
    if not CAPTURE_JS.exists():
        print(f"  ⚠️  capture.js not found at {CAPTURE_JS}")
        return False

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        suffix=".html", delete=False, mode="w", encoding="utf-8"
    ) as f:
        f.write(html_content)
        tmp_html = f.name

    try:
        result = subprocess.run(
            [
                "node", str(CAPTURE_JS),
                tmp_html,
                str(out_path),
                str(width),
                "800",
                "fullpage",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            print(f"  ✅ {out_path.name} → {out_path}")
            return True
        else:
            print(f"  ❌ capture failed: {result.stderr[:300]}")
            return False
    except subprocess.TimeoutExpired:
        print("  ❌ capture timeout")
        return False
    except FileNotFoundError:
        print("  ❌ node not found — is Node.js installed?")
        return False
    finally:
        Path(tmp_html).unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# 便捷函数
# ══════════════════════════════════════════════════════════════════════════════

def generate_post_card(
    post: dict,
    out_path: Path,
    eyebrow: str = "",
    theme: dict | None = None,
) -> bool:
    """生成帖子卡片 PNG，返回是否成功。"""
    html_content = make_post_card_html(post, eyebrow=eyebrow, theme=theme)
    return capture_card(html_content, out_path)


def generate_summary_card(
    ai_repos: list[dict],
    out_path: Path,
    slot: str = "日报",
    today_cn: str = "",
) -> bool:
    """生成热榜总览卡片 PNG，返回是否成功。"""
    html_content = make_summary_card_html(ai_repos, slot=slot, today_cn=today_cn)
    return capture_card(html_content, out_path)
