# 📱 AI 日报

> 每天早上 8 点自动抓取 AI 圈热点，生成「AI炼丹师」风格小红书内容 + Qwen 封面图，以 GitHub Issue 形式发布。

## ✨ 效果预览

每天自动生成一个 Issue，包含 4 篇帖子，每篇含：
- 📌 封面标题（震惊体）
- 🖼️ Qwen Wanx 生成的封面图
- 📝 小红书风格正文（干货 + emoji）
- 🏷️ 10 个话题标签

数据来源：**HackerNews** + **GitHub Trending**（无需额外 API Key）

---

## 🚀 快速开始（3 步）

### Step 1：Fork 此仓库

点击右上角 **Fork** → 创建你自己的副本

### Step 2：设置 Secrets

进入仓库 **Settings → Secrets and variables → Actions → New repository secret**，添加以下密钥：

| Secret 名称 | 必填 | 说明 |
|---|---|---|
| `DASHSCOPE_API_KEY` | ✅ 推荐 | 阿里云 DashScope API Key（用于 Wanx 图像生成）[获取地址](https://dashscope.aliyun.com/) |
| `LLM_API_KEY` | ✅ 推荐 | OpenAI 兼容 API Key（用于内容生成）|
| `LLM_BASE_URL` | 可选 | API Base URL，默认 `https://api.openai.com/v1` |
| `LLM_MODEL` | 可选 | 模型名称，默认 `gpt-4o-mini` |

> **注意：** 不配置 API Key 时，会使用模板内容（无图片），仍可正常创建 Issue。

### Step 3：启用 GitHub Actions

进入仓库 **Actions → I understand my workflows, enable them**

完成！之后每天北京时间 **8:00** 自动触发。

---

## 🔧 手动触发

**Actions → 📱 AI 日报 → Run workflow → Run workflow**

可选择执行阶段（`generate` / `issue` / `all`），默认 `all`。

---

## 🏗️ 项目结构

```
ai-xiaohongshu-daily/
├── .github/
│   └── workflows/
│       └── daily.yml          # GitHub Actions 定时任务
├── scripts/
│   └── generate_post.py       # 核心脚本（数据抓取 + 内容生成 + 图片生成 + Issue 创建）
├── assets/                    # 自动提交的封面图（按日期归档）
│   └── YYYY-MM-DD/
│       ├── cover1.png
│       ├── cover2.png
│       ├── cover3.png
│       └── cover4.png
├── posts_data.json            # 当日生成的帖子数据（workflow 内部中间文件）
├── requirements.txt
└── README.md
```

---

## 🔄 工作流程

```
GitHub Actions 触发（每天 00:00 UTC）
    │
    ├── 1. 抓取数据
    │       ├── HackerNews Top Stories（过滤 AI 关键词）
    │       └── GitHub Trending（近 7 天高 Star 的 AI 项目）
    │
    ├── 2. LLM 生成内容（gpt-4o-mini 或自定义模型）
    │       └── 4 篇小红书帖子（标题 + 正文 + 标签 + 图片 prompt）
    │
    ├── 3. Wanx 生成封面图（并发提交，依次下载）
    │       └── assets/YYYY-MM-DD/cover1~4.png
    │
    ├── 4. git commit & push（图片进仓库）
    │
    └── 5. 创建 GitHub Issue
            └── 包含图片引用（raw.githubusercontent.com）
```

---

## 🛠️ 本地调试

```bash
git clone https://github.com/your-username/ai-xiaohongshu-daily
cd ai-xiaohongshu-daily
pip install -r requirements.txt

# 设置环境变量
export DASHSCOPE_API_KEY="your-key"
export LLM_API_KEY="your-key"
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL="gpt-4o-mini"
export GITHUB_TOKEN="your-pat-token"
export GITHUB_REPOSITORY="your-username/ai-xiaohongshu-daily"

# 仅生成内容（不创建 Issue）
python scripts/generate_post.py --phase generate

# 仅创建 Issue（需先运行 generate）
python scripts/generate_post.py --phase issue

# 全流程
python scripts/generate_post.py --phase all
```

---

## 📊 API 用量参考

每次运行（4 篇帖子）：
- **DashScope Wanx**：4 次图片生成（wanx2.1-t2i-turbo，约 ¥0.08/张）
- **LLM**：约 2000 input tokens + 2000 output tokens（gpt-4o-mini 约 $0.003）

月度成本估算：**< ¥20**

---

## 📄 License

MIT
