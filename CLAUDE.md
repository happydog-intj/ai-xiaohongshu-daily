# AI 日报 — 项目知识库

## 项目概述

每天自动抓取 HackerNews / GitHub Trending AI 热点，用 LLM 生成 ljg-plain 白话风格帖子（含封面图），发布为 GitHub Issue。

- 主脚本：`scripts/generate_post.py`
- 工作流：`.github/workflows/daily.yml`（每天 UTC 00:00 = 北京时间 08:00 触发）
- 封面图：`assets/{日期}/cover{1-4}.png`（ljg-card Playwright 生成，1080px 长图）

---

## 封面标题策略 — ljg-plain 白话原则

封面两行让人立刻知道「这件事是什么 + 最值得看的一点」，不制造悬念，不耍花招。

### 封面两行结构

```
第一行（≤10字）= 直接说清楚这件事是什么，不用句号
第二行（≤12字）= 最重要的一个具体细节或结果（数字/名字/动作）
```

### 五条铁律

1. **具体胜于模糊** — 「每天自动跑 50 个实验」好过「AI 研究神器」
2. **诚实胜于夸张** — 写真实发生的事，不用冲击词
3. **短词优先** — 能两个字说的不用四个字
4. **不制造假悬念** — 读完标题应该知道这是什么，不是更困惑
5. **直接点名** — 涉及具体的人、公司、数字，直接说出来

**禁止**：悬念钩子、情绪操控词（偷偷/悄悄/内幕/泄露/爆了/炸了/碾压）、虚假对比体

### 正文风格 — ljg-plain 白话原则

正文是从头流到尾的连贯散文，**不用编号分点、不用小标题、不堆 emoji**。像跟聪明朋友说话，让他一下子 grok（懂透）。

**九条铁律（顺序即优先级）：**

1. **口语检验** — 读出声来，你会这样跟朋友说吗？不会就改到会
2. **零术语** — 专业词必须先用大白话把意思落地，再顺带提名字
3. **短词优先** — 能两个字说的不用四个字；「进行分析」→「看」
4. **一句一事** — 每句只推进一步，长句拆短
5. **具体** — 名词看得见，动词有力气；「情况不太好」→「项目三天没人提交代码」
6. **开头给理由** — 第一句让人想读下一句，不铺垫、不「自古以来」
7. **不填充** — 删开场白、拐杖词，每句都在干活
8. **信任读者** — 说一遍够了，不反复解释
9. **诚实** — 「大概 70%」比「可能」诚实

**结尾**：一个读者真的会想回答的具体问题，不用套路互动公式。

---

## GitHub Trending AI 追踪（第二功能）

### 触发时间
- 北京时间 08:00 → **早报**
- 北京时间 21:00 → **晚报**
- 工作流：`.github/workflows/trending.yml`
- 脚本：`scripts/trending_issue.py`

### 流程
```
GitHub Trending 页面（每日榜 Top 10）
    ↓ BeautifulSoup 抓取
过滤 AI 关键词（含 llm/agent/diffusion/mcp 等 30+ 关键词）
    ↓
LLM 生成小红书风格帖子（同 daily 风格）
    ↓
创建 GitHub Issue（标签：trending + ai-content）
    ↓
飞书逐条推送（汇总头 + 每帖一条）
```

### Issue 结构
1. 今日 AI 热榜总览（所有 AI 项目列表，带 Star 数）
2. 精选帖子详情（封面标题 + 正文 + 标签）

### 手动触发
```bash
gh workflow run "🔥 GitHub Trending AI 追踪" --field since=daily --field max_posts=4
gh run list --workflow="🔥 GitHub Trending AI 追踪" --limit 3
```

### 本地调试
```bash
export LLM_API_KEY="..."
export GITHUB_TOKEN="..."
export GITHUB_REPOSITORY="your-username/ai-xiaohongshu-daily"
export FEISHU_WEBHOOK="..."
python scripts/trending_issue.py --since daily --max-posts 4
# 仅本地测试（不发 issue / 不推飞书）
python scripts/trending_issue.py --no-issue --no-notify
```

---

## 运维经验

### Git 推送冲突

`git push` 失败（rejected / fetch first）原因：两次 workflow 并发时远端已有新提交。

**解决方案**（已写入 `daily.yml`）：
```bash
git pull --rebase origin master
git push
```

本地操作遇到未暂存变更时：
```bash
git stash && git pull --rebase origin master && git stash pop && git push
```

### 触发一次 Action（手动）

```bash
gh workflow run "📱 AI 日报" --field phase=all
gh run list --workflow="📱 AI 日报" --limit 3
```

### Node.js 版本警告

`actions/checkout@v4` 和 `actions/setup-python@v5` 会产生 Node.js 20 弃用警告，不影响运行。2026 年 6 月前不需要处理。

---

## HN & a16z 日报（第三功能）

### 触发时间
- 北京时间 09:00（每天早报）
- 工作流：`.github/workflows/news_digest.yml`
- 脚本：`scripts/news_digest.py`（主流程）+ `scripts/fetch_news.py`（抓取模块）

### 流程
```
HackerNews API Top N（过滤无URL条目，取有外链帖子）
a16z RSS Feed Latest N（备用：HTML抓取 a16z.com/posts）
    ↓ 抓取正文摘要（前1000字）
LLM 批量翻译标题 + 生成中文摘要（一次 API 调用）
    ↓
card_generator.generate_news_card() → PNG 卡片
    ↓ 简洁双语卡片：原文标题 / 中文标题 / 摘要 / 来源/评论数
飞书推送（App API 图片消息 + 文字链接；降级 Webhook 纯文字）
```

### 卡片设计
- **HackerNews**：橙色主题（`#FF6900`），显示分数+评论数
- **a16z**：紫色主题（`#6B5CE7`），显示域名
- 双语展示：英文原题（黑色）+ 中文翻译（彩色）
- 底部：中文摘要 80-120 字

### 手动触发
```bash
gh workflow run "📰 HN & a16z 日报" --field hn=8 --field a16z=5
gh run list --workflow="📰 HN & a16z 日报" --limit 3
```

### 本地调试
```bash
export LLM_API_KEY="..."
export FEISHU_APP_ID="..." FEISHU_APP_SECRET="..." FEISHU_USER_ID="..."
# 完整运行
python scripts/news_digest.py --hn 5 --a16z 5
# 预览不发送
python scripts/news_digest.py --dry-run
# 跳过图片（纯文字）
python scripts/news_digest.py --no-card --dry-run
```

---

## LLM 配置

| 环境变量 | 说明 |
|---|---|
| `LLM_API_KEY` | OpenAI 兼容 API Key |
| `LLM_BASE_URL` | API 基础 URL（默认 `https://api.openai.com/v1`）|
| `LLM_MODEL` | 模型名（默认 `gpt-4o-mini`）|
| `FEISHU_WEBHOOK` | 飞书自定义机器人 Webhook URL（可选，降级使用）|
| `FEISHU_APP_ID` | 飞书 App ID（发私信图片必需）|
| `FEISHU_APP_SECRET` | 飞书 App Secret（发私信图片必需）|
| `FEISHU_USER_ID` | 飞书接收人 User ID（私信目标）|
| `DASHSCOPE_API_KEY` | 阿里云 DashScope（备用）|
