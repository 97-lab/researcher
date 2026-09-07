# 本地深度研究员（Local Deep Researcher）

一个跑在本地、用自然语言指挥的“研究者 Agent”。你给它一个研究主题，它会自动搜索网络资料，多轮搜索、总结、反思，最终产出一份带参考来源的研究报告。

本项目是一个学习型复刻项目，研究循环参考了 [langchain-ai/local-deep-researcher](https://github.com/langchain-ai/local-deep-researcher)，并在其基础上扩展了两套记忆能力：

- **分支记忆 + 时间旅行**：每次研究是一个独立分支（r1、r2…），你可以回到任意一轮搜索之前，换一个问题重新研究，产生新版本；
- **RAG 版本记忆**：每个版本都会被向量化存档，覆盖后你依然能用一句自然语言找回“旧版本说过什么”。

## 功能一览

- 完全本地的对话模型（Ollama），不需要任何云端 LLM
- LangGraph 反思循环：`搜索 → 总结 → 反思 → 继续搜索或收尾`
- Tavily 联网搜索 + 相关性过滤 + 来源去重
- 自然语言指令解析：新研究 / 查看 / 追问 / 历史记忆检索 / 退出
- 流式输出：总结生成时逐字显示，不用等全部生成完
- 所有状态本地持久化：SQLite（检查点 + 分支）+ Chroma（RAG 历史版本）

## 项目结构

```
.
├── main.py                      # 入口：自然语言对话循环
├── branch_store.py              # 分支当前版本表（SQLite）
├── requirements.txt
├── .env.example                 # 环境变量模板
├── deep_researcher/
│   ├── graph.py                 # LangGraph 图：节点与流转
│   ├── state.py                 # 图状态定义
│   ├── configuration.py         # 从 .env 读取配置
│   ├── tools.py                 # Tavily 搜索 + 相关性过滤
│   ├── memory.py                # RAG 记忆：remember / recall
│   ├── schemas.py               # 结构化输出模型
│   ├── prompts.py               # 各节点的提示词
│   └── utils.py                 # 搜索词校验等小工具
└── test_scripts/
    ├── memory_test.py           # RAG 记忆独立测试
    └── test_json.py             # JSON 输出解析测试
```

## 工作原理

### 1. 研究循环

一个分支的研究流程如下：

```
生成搜索词
    ↓
联网搜索（Tavily）
    ↓
总结已有资料
    ↓
反思：总结还缺什么？
    ↓
还有知识盲区 → 回到“联网搜索”
总结已完整 → 附上参考来源，收尾
```

循环次数由 `MAX_WEB_RESEARCH_LOOPS` 控制。

### 2. 分支与时间旅行

每次新研究生成一个 `researcher_id`（如 r1）。LangGraph 的 SQLite 检查点会保留整条历史时间线，因此你可以说“回到 r1 第 2 轮，重点查祖冲之的算法”，程序会把那一轮搜索词替换成你的新问题，再从这个时间点往后重跑。

### 3. RAG 版本记忆

每个分支的每个研究结果（搜索词 + 总结）都会同时写入两处：

- `branches.sqlite`：只保留该分支的最新版本；
- `memory_store/`（Chroma 向量库）：追加保存全部历史版本。

检索时程序用你的原话做语义搜索，默认相关度阈值 `0.3`，把无关旧记忆过滤掉。

## 环境要求

- Windows / macOS / Linux，Python 3.10+
- [Ollama](https://ollama.com) 已安装并运行
- Tavily API Key（[注册获取](https://tavily.com)）

## 安装与运行

### 1. 拉取本地模型

```bash
ollama pull qwen2.5:3b
ollama pull qwen3-embedding:0.6b
```

`qwen2.5:3b` 用于意图解析、搜索词生成、总结；`qwen3-embedding:0.6b` 用于把历史版本转成向量。想换更强的总结模型也可以 `ollama pull qwen2.5:7b` 后改 `.env`。

### 2. 安装依赖

```bash
python -m venv .venv
```

Windows：

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
```

macOS / Linux：

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少填写：

```ini
TAVILY_API_KEY=你的key
EMBEDDING_MODEL=qwen3-embedding:0.6b
```

常用变量：

| 变量 | 作用 | 示例 |
|---|---|---|
| `TAVILY_API_KEY` | 联网搜索密钥 | `tvly-xxxx` |
| `OLLAMA_BASE_URL` | Ollama 服务地址 | `http://localhost:11434` |
| `INTENT_LLM` | 自然语言意图解析 | `qwen2.5:3b` |
| `QUERY_LLM` | 生成搜索词 | `qwen2.5:3b` |
| `SUMMARIZE_LLM` | 生成/整合总结 | `qwen2.5:3b` |
| `REFLECT_LLM` | 反思总结、找知识盲区 | `qwen2.5:3b` |
| `EMBEDDING_MODEL` | RAG 记忆向量模型 | `qwen3-embedding:0.6b` |
| `MAX_WEB_RESEARCH_LOOPS` | 单个分支最多研究轮数 | `3` |
| `RELEVANCE_RATIO` | 搜索结果相关性过滤强度 | `0.3` |

> 注意：`.env` 里的变量不要写成空值。例如 `EMBEDDING_MODEL=` 会覆盖代码里的默认值，导致“模型名为空”的报错。

### 4. 启动

```bash
python main.py
```

## 怎么和它对话

| 你想做什么 | 这样说 |
|---|---|
| 新研究 | 帮我研究一下圆周率的计算历史 |
| 查看分支当前结果 | 看看 r1 的研究结果 |
| 回到历史时间点追问 | 回到 r1 第1轮，重点查祖冲之的算法 |
| 找回被覆盖的旧版本 | r1 以前对精度的总结是什么 |
| 退出 | 退出 |

解析完成后程序会先打印一行：

```
解析结果: {'action': 'recall', 'researcher_id': 'r1', ...}
```

你可以据此判断系统把你的话理解成了哪种操作。

## 本地会生成哪些数据文件

| 文件 / 目录 | 作用 |
|---|---|
| `research.sqlite` | LangGraph 检查点，支撑时间旅行 |
| `branches.sqlite` | 分支当前版本 |
| `memory_store/` | Chroma 向量库，保存所有历史版本 |
| `.env` | 你的私密配置 |

这些文件都已经加入 `.gitignore`，不会被推送到 GitHub。

## 常见问题

### Ollama 提示模型找不到

```bash
ollama pull qwen2.5:3b
ollama pull qwen3-embedding:0.6b
```

### 报错 `model should have at least 1 character`

检查 `.env`，确认 `EMBEDDING_MODEL=qwen3-embedding:0.6b` 等号右边有值，不能是空行。

### 报错缺少 `TAVILY_API_KEY`

在 Tavily 官网注册并复制 Key，填进 `.env` 后重启程序。

### 总结模型用 deepseek-r1 配合 JSON 模式报 500

JSON 结构化输出建议使用 `qwen2.5:3b` 等普通对话模型；反思模型同理。

## 参考

- [langchain-ai/local-deep-researcher](https://github.com/langchain-ai/local-deep-researcher)：研究循环思路来源
- [CrewAI memory/storage/rag_storage.py](https://github.com/crewAIInc/crewAI/blob/main/lib/crewai/src/crewai/memory/storage/rag_storage.py)：RAG 记忆层设计参考
- [LangGraph](https://github.com/langchain-ai/langgraph)、[Chroma](https://github.com/chroma-core/chroma)
