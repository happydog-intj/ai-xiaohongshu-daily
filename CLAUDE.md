# AI 小红书日报 — 项目知识库

## 项目概述

每天自动抓取 HackerNews / GitHub Trending AI 热点，用 LLM 生成小红书风格帖子（含封面图），发布为 GitHub Issue。

- 主脚本：`scripts/generate_post.py`
- 工作流：`.github/workflows/daily.yml`（每天 UTC 00:00 = 北京时间 08:00 触发）
- 封面图：`assets/{日期}/cover{1-4}.png`（Pillow 生成，1080×1080 白底黑字）

---

## 小红书爆款标题策略

### 人名/公司锚点优先级

使用以下锚点可显著提升点击率（按效果排序）：

1. **知名人物点名**：马斯克、黄仁勋、Sam Altman、LeCun、Hinton、Pichai、苏姿丰
2. **大公司竞争对比**：OpenAI vs 谷歌 / Meta / Anthropic / 苹果 / 微软
3. **明星产品对决**：ChatGPT vs Claude vs Gemini vs Copilot vs Llama
4. 以上都没有时 → 用数字体或「偷偷/悄悄」内幕体

### 封面两行结构铁律

```
第一行（≤10字）= 钩子：制造悬念/冲突/好奇，不写结论，不用句号
第二行（≤12字）= 揭晓/强化：补充关键信息或情绪反转，用！或…结尾
```

禁止：两行都完整句 / 两行都是问句 / 两行主题不一致

### 5大爆款标题公式

| 公式 | 第一行 | 第二行 |
|---|---|---|
| 人名+惊人行为 | `[名人]偷偷做了这件事` | `[情绪词]！[补充细节]` |
| 产品战争体 | `[产品A]这次真的[吊打/超越]了` | `[产品B]彻底慌了！` |
| 身份反差体 | `[高薪职业/年限]` | `被$0 AI替了` |
| 数字实测体 | `我用AI[时间][做了什么]` | `[N]倍速！结果出乎意料` |
| 内幕悄悄体 | `[大公司]悄悄上线了` | `90%用户还不知道！` |

### 情绪触发词（必选其一）

- **冲击词**：爆了 / 炸了 / 王炸 / 暴打 / 碾压 / 吊打
- **好奇词**：偷偷 / 悄悄 / 内部 / 泄露 / 隐藏 / 没公开
- **反差词**：竟然 / 没想到 / 原来 / 但其实
- **亲测词**：实测 / 亲测 / 踩坑 / 真的能 / N倍

### 正文开头钩子

- ✅ 用：「刚看到」「实测刚完成」「你不知道的是」「圈内没人说破的」
- ❌ 禁：「今天」「最近」「现在」等模糊时间词

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
gh workflow run "📱 AI 小红书日报" --field phase=all
gh run list --workflow="📱 AI 小红书日报" --limit 3
```

### Node.js 版本警告

`actions/checkout@v4` 和 `actions/setup-python@v5` 会产生 Node.js 20 弃用警告，不影响运行。2026 年 6 月前不需要处理。

---

## LLM 配置

| 环境变量 | 说明 |
|---|---|
| `LLM_API_KEY` | OpenAI 兼容 API Key |
| `LLM_BASE_URL` | API 基础 URL（默认 `https://api.openai.com/v1`）|
| `LLM_MODEL` | 模型名（默认 `gpt-4o-mini`）|
| `DASHSCOPE_API_KEY` | 阿里云 DashScope（备用）|
