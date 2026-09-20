# 本地深度研究员（Local Deep Researcher）

一个跑在本地的“研究者 Agent”。你给它一个研究主题，它会自动生成搜索词、联网查资料、多轮总结与反思，最后产出一份带参考来源的研究报告。

本项目是一个学习型复刻项目，研究循环参考了 [langchain-ai/local-deep-researcher](https://github.com/langchain-ai/local-deep-researcher)，并在此基础上扩展了：

- **分支记忆**：一个研究主题对应一个分支编号（r1、r2…）；
- **时间旅行**：回到某一轮搜索之前，换一个问题重新研究，产生新版本；
- **RAG 版本记忆**：每个版本都会被向量化存档，覆盖后依然能用自然语言找回旧版本；
- **工具运行时**：所有能力通过 ToolRegistry 统一注册、校验、调用；
- **上下文构建**：用 HistoryProcessor 控制历史长度，避免 prompt 无限膨胀；
- **规划者 Agent**：研究开始前先生成研究简报和子问题；
- **模型路由**：按角色选择快模型或质量模型，JSON 输出失败自动重试；
- **轨迹与评测**：每次运行写入 `runs/*.jsonl`，评测脚本守护已有功能；
- **对话理解**：结合最近几轮对话补全代词、省略和主题延续；
- **歧义澄清**：指代不明时先反问，用户回答后再继续原任务。

## 当前版本亮点

- 全程本地对话模型（Ollama），不依赖云端 LLM
- LangGraph 反思循环：搜索 → 总结 → 反思 → 继续搜索或收尾
- Tavily 联网搜索 + 相关性过滤 + 来源去重
- 研究完成后输出最终总结和参考来源
- 自然语言控制：新研究 / 继续研究 / 查看 / 追问 / 历史检索 / 退出
- 工具注册表：`web_search` 与 `recall_memory` 统一管理
- 上下文管理：只保留最近 N 轮搜索资料，单条过长自动截断
- 模型路由：`fast` / `quality` 档位，角色级模型覆盖，JSON 自动重试
- 规划者 Agent：先写研究简报和子问题，研究者按提纲执行
- 对话记忆：保存最近几轮对话、当前活跃主题和待澄清问题
- 歧义反问：指代不明时暂停任务，等用户输入澄清答案
- 主题与分支编号一一对应：同一主题复用编号，新主题分配新编号
- 四套本地存储：精确时间线、当前分支、RAG 历史记忆、会话记忆
- 轨迹记录：每次运行、每个节点、每次工具调用写入 `runs/*.jsonl`
- 自动评测：`eval_research.py` 覆盖上下文、工具、轨迹、分支、记忆、模型路由
- 终端降噪：研究过程只显示“思考中...”，最终只输出总结和参考来源

## 工作流程

### 1. 对话理解与意图路由

```
用户自然语言
   ↓
读取会话上下文（活跃主题、最近几轮、分支列表）
   ↓
understand_message（代词消解、省略补全、主题延续）
   ↓
new_research / continue_research / answer_from_memory
view / follow_up / recall / exit
```

| 动作 | 含义 | 走哪条路 |
|---|---|---|
| `new_research` | 研究新主题 | 创建或复用主题分支，运行完整研究图 |
| `continue_research` | 同一主题继续追问 | 自动匹配分支，追加一轮研究 |
| `answer_from_memory` | 历史总结足够回答 | 直接从 RAG 记忆生成回答 |
| `view` | 查看当前版本 | 读 BranchStore |
| `follow_up` | 回到某轮重新研究 | 用 checkpoint 做时间旅行 |
| `recall` | 找回被覆盖的旧版本 | 调 RAG 记忆工具 |
| `exit` | 退出 | 结束程序 |

如果代词或主题不明确，会先进入澄清流程：

```
用户：他得过哪些奖项？
Agent：你指的是哪位？
       1. 沈石溪
       2. 曹文轩
用户：沈石溪
Agent：按“沈石溪获得过哪些奖项”继续。
```

### 2. 一次新研究的图流程

```
START
  ↓
plan_research       规划者 Agent：先生成研究简报和子问题
  ↓
recall_history      先从 RAG 里召回相关历史记忆
  ↓
generate_query      生成搜索词
  ↓
web_research        通过 ToolRegistry 调 web_search
  ↓
summarize_sources   用 ContextBuilder 构建上下文并流式总结
  ↓
reflect_on_summary  反思知识盲区
  ↓
route_research
  ├── 继续搜索 → 回到 web_research
  └── 已完成   → finalize_summary
                     ↓
                    END
```

### 3. 一次追问（时间旅行）

```
用户：回到 r1 第1轮，重点查祖冲之的算法
   ↓
在 research.sqlite 的检查点历史里找到“第1轮搜索前”的快照
   ↓
把那一轮的 search_query 替换成追问内容
   ↓
从该时间点继续往后跑
   ↓
产生新版本，写入 BranchStore 和 MemoryStore
```

## 分支编号规则

当前版本的原则是：**主题是身份，编号只是名字。**

- 第一次研究“圆周率” → 创建 r1；
- 第一次研究“亚里士多德” → 创建 r2；
- 再次研究“圆周率” → 复用 r1，不新建编号。

实现要点：

- `BranchStore` 新增 `topic_key` 字段和 `meta` 编号计数器；
- `get_or_create_by_topic()` 按主题查重，找不到才分配新编号；
- 编号计数器持久化在 `branches.sqlite` 的 `meta` 表里；
- `main.py` 里的数据库路径统一到项目根目录，避免换个工作目录又重新从 r1 开始。

> 注意：不要单独删除 `branches.sqlite`、`research.sqlite` 或 `memory_store/` 中的一个。只删其中一个，会导致编号、检查点和历史记忆不一致。要清空测试数据时，应该关闭程序后一起删除这三类数据。

## 项目结构

```
.
├── main.py                        # 入口：对话循环、意图路由、时间旅行
├── branch_store.py                # 主题 ↔ 分支编号映射 + 当前版本
├── requirements.txt
├── .env.example                   # 环境变量模板
├── README.md
├── deep_researcher/
│   ├── graph.py                   # LangGraph 图：节点与流转
│   ├── state.py                   # 图状态定义
│   ├── configuration.py           # 从 .env 读取配置
│   ├── context.py                 # ContextBuilder + HistoryProcessor
│   ├── conversation.py            # 会话记忆、代词消解、歧义澄清
│   ├── memory.py                  # RAG 记忆：remember / recall
│   ├── model_router.py            # 按角色选模型、JSON 自动重试
│   ├── tool_registry.py           # 工具注册表：登记、校验、调用
│   ├── tool_specs.py              # web_search / recall_memory 注册
│   ├── tools.py                   # Tavily 搜索与相关性过滤
│   ├── trace.py                   # 运行轨迹：节点 / 工具 / 异常
│   ├── prompts.py                 # 各节点提示词
│   ├── schemas.py                 # 结构化输出模型
│   └── utils.py                   # 搜索词校验、来源去重
└── test_scripts/
    ├── eval_research.py           # 自动回归评测
    ├── test_tool_registry.py      # 工具注册表测试
    ├── test_context.py            # 上下文裁剪测试
    ├── memory_test.py             # RAG 记忆独立测试
    └── test_json.py               # JSON 解析测试
```

## 架构分层

### 交互层：`main.py`

- 读取用户输入；
- 通过 `ModelRouter("intent")` 调模型解析成 `UserIntent`；
- 根据动作路由到新研究、查看、追问、历史检索；
- 组装 `MemoryStore` 与 `ToolRegistry`，交给图使用；
- 每次研究/追问/召回创建 `TraceRecorder`；
- 统一保存研究结果到 BranchStore 和 MemoryStore。

### 会话层：`deep_researcher/conversation.py`

- 保存最近几轮对话、活跃主题、活跃分支和待澄清问题；
- `understand_message()`：结合上下文做代词消解和省略补全；
- `resolve_clarification()`：解析用户对反问的回答；
- `answer_from_memory()`：优先用历史记忆回答，不够再继续研究。

### 编排层：`deep_researcher/`

- `graph.py`：LangGraph 节点与边，包含规划者和研究者两个角色；
- `state.py`：图状态，列表字段用 `Annotated[list, operator.add]` 累加；
- `context.py`：历史裁剪与上下文拼装；
- `configuration.py`：读取模型名、循环次数、上下文预算等配置；
- `prompts.py`：搜索词、总结、反思、意图解析的提示词。

### 模型层：`configuration.py` + `model_router.py`

- `MODEL_PROFILE`：`fast` / `quality` 档位；
- `MODEL_ROUTES`：`conversation`、`intent`、`planner`、`reviewer`、`query`、`summarize`、`reflect` 的角色路由；
- `ModelRouter.invoke_json()`：JSON 解析失败自动追问和重试；
- 角色专用环境变量优先级最高。

### 观测与评测层：`trace.py` + `eval_research.py`

- `trace.py`：每次运行写 `runs/*.jsonl`，记录节点耗时、工具调用、异常；
- `eval_research.py`：不需要 Ollama 和网络，快速验证核心行为是否退化。

### 工具层：`tool_registry.py` + `tool_specs.py` + `tools.py`

工具统一流程：

```
找工具 → 查权限 → 校验参数 → 执行 handler → 返回结果
```

当前注册了两个工具：

| 工具 | 作用 | 权限 |
|---|---|---|
| `web_search` | 联网搜索、过滤无关结果、返回统一观察 | network |
| `recall_memory` | 从 RAG 历史版本库召回相关总结 | safe |

### 存储层

| 存储 | 文件 / 目录 | 存什么 | 特点 |
|---|---|---|---|
| LangGraph Checkpoint | `research.sqlite` | 每个状态的完整时间线 | 支持时间旅行 |
| BranchStore | `branches.sqlite` | 主题与当前版本 | 主题查重、编号持久化 |
| MemoryStore | `memory_store/` | 所有历史版本的向量 | 追加式、语义召回 |
| ConversationStore | `conversation.sqlite` | 最近对话、活跃主题、待澄清问题 | 支持聊天式上下文 |

三者分工：

- Checkpoint 是给机器用的精确状态快照；
- BranchStore 是给用户用的当前分支指针；
- MemoryStore 是给自然语言模糊回忆用的历史档案馆。

## 上下文管理

`context.py` 提供两级控制：

1. `LastNObservations`：总结时只保留最近 N 轮搜索资料；
2. `TruncateEachObservation`：单轮搜索资料过长时自动截断。

`ContextBuilder` 负责把它们和已有总结、RAG 历史记忆拼成完整上下文。

相关配置：

```ini
CONTEXT_KEEP_LAST_OBSERVATIONS=2
CONTEXT_MAX_OBSERVATION_CHARS=4000
CONTEXT_MAX_MEMORY_CHARS=2000
```

## RAG 版本记忆

每次研究完成，`MemoryStore.remember()` 会把一个完整版本写入 Chroma：

```
研究主题：...
搜索词：...
总结：...
```

元数据包含：

- `researcher_id`
- `thread_id`
- `topic`
- `kind`
- `queries`
- `remembered_at`

`recall_memory` 用自然语言查询，按相关度过滤。当前实现细节：

- 向量模型：`qwen3-embedding:0.6b`；
- Chroma collection 使用 L2 距离，返回平方 L2 距离；
- qwen3-embedding 向量已归一化，因此相关度换算为：

```text
余弦相似度 = 1 - distance / 2
```

- 默认门槛：`min_score = 0.3`。
- `thread_id` 用于精确到具体分支，避免不同主题的旧记忆混在一起。

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

至少填写：

```ini
TAVILY_API_KEY=你的key
EMBEDDING_MODEL=qwen3-embedding:0.6b
```

### 4. 启动

```bash
python main.py
```

## 怎么和它对话

| 你想做什么 | 这样说 |
|---|---|
| 新研究 | 帮我研究一下圆周率 |
| 查看当前版本 | 看看 r1 现在的结果 |
| 回到历史时间点追问 | 回到 r1 第1轮，重点查祖冲之的算法 |
| 找回被覆盖的旧版本 | r1 以前对气候影响的总结是什么？ |
| 全局找回旧版本 | 我之前研究过亚里士多德吗？当时怎么总结的？ |
| 退出 | 退出 |

连续追问示例：

```text
用户：对沈石溪进行介绍
Agent：思考中...
Agent：（最终总结和参考来源）

用户：他得过哪些奖项？
Agent：思考中...
Agent：（按“沈石溪获得过哪些奖项”继续研究或直接回答）
```

终端输出规则：

- 研究过程中只显示 `Agent：思考中...`
- 最终只显示最终总结和参考来源
- 不显示模型路由、意图 JSON、节点日志、相关度和分支元数据

## 常用配置

| 变量 | 作用 | 示例 |
|---|---|---|
| `TAVILY_API_KEY` | 联网搜索密钥 | `tvly-xxxx` |
| `OLLAMA_BASE_URL` | Ollama 服务地址 | `http://localhost:11434` |
| `CONVERSATION_LLM` | 对话理解/代词消解模型 | `qwen2.5:3b` |
| `INTENT_LLM` | 意图解析模型 | `qwen2.5:3b` |
| `PLANNER_LLM` | 规划者模型 | `qwen2.5:3b` |
| `REVIEWER_LLM` | 审核者模型 | `qwen2.5:3b` |
| `QUERY_LLM` | 搜索词生成模型 | `qwen2.5:3b` |
| `SUMMARIZE_LLM` | 总结模型 | `qwen2.5:3b` |
| `REFLECT_LLM` | 反思模型 | `qwen2.5:3b` |
| `MODEL_PROFILE` | 模型档位：fast / quality | `fast` |
| `FAST_LLM` | 快模型 | `qwen2.5:3b` |
| `QUALITY_LLM` | 质量模型 | `qwen2.5:7b` |
| `MODEL_MAX_RETRIES` | JSON 失败重试次数 | `2` |
| `MAX_REVIEW_ROUNDS` | 审核者最多允许补搜轮数 | `1` |
| `EMBEDDING_MODEL` | RAG 向量模型 | `qwen3-embedding:0.6b` |
| `MAX_WEB_RESEARCH_LOOPS` | 单个分支最多研究轮数 | `3` |
| `SEARCH_MAX_RESULTS` | 单次搜索最多取回条数 | `10` |
| `SEARCH_KEEP_RESULTS` | 相关性过滤后最多保留条数 | `3` |
| `RELEVANCE_RATIO` | 搜索结果相关性过滤强度 | `0.3` |
| `CONTEXT_KEEP_LAST_OBSERVATIONS` | 总结时保留最近几轮资料 | `2` |
| `CONTEXT_MAX_OBSERVATION_CHARS` | 单轮搜索资料最大字符数 | `4000` |
| `CONTEXT_MAX_MEMORY_CHARS` | 注入的历史记忆最大字符数 | `2000` |

## 测试

在项目根目录运行：

```powershell
python -m test_scripts.eval_research
python -m test_scripts.test_tool_registry
python -m test_scripts.test_context
python -m test_scripts.memory_test
```

分别验证：

- `eval_research`：当前 8 项离线评测，覆盖上下文、工具、轨迹、分支映射、记忆相关度、规划者上下文、模型路由和 JSON 重试；
- 工具注册、权限、参数校验；
- 上下文裁剪与历史记忆注入；
- RAG 记忆的写入与召回。

连续对话、代词消解和歧义澄清目前作为下一步评测扩展项。

`eval_research`、`test_tool_registry`、`test_context` 不需要网络和 Ollama；`memory_test` 需要 Ollama 正在运行并已拉取 `qwen3-embedding:0.6b`。

## 本地数据文件

| 文件 / 目录 | 作用 | 是否提交 Git |
|---|---|---|
| `research.sqlite` | LangGraph 检查点，支撑时间旅行 | 否 |
| `branches.sqlite` | 主题分支映射与当前版本 | 否 |
| `memory_store/` | Chroma 向量库，保存历史版本 | 否 |
| `conversation.sqlite` | 最近对话和会话状态 | 否 |
| `.env` | 私密配置 | 否 |

这些文件已经加入 `.gitignore`。

## 常见问题

### Ollama 提示模型找不到

```bash
ollama pull qwen2.5:3b
ollama pull qwen3-embedding:0.6b
```

### 报错 `model should have at least 1 character`

检查 `.env`，确认 `EMBEDDING_MODEL=qwen3-embedding:0.6b` 等号右边有值，不能是空值。

### 报错缺少 `TAVILY_API_KEY`

在 Tavily 官网注册并复制 Key，填进 `.env` 后重启程序。

### 总结模型用 deepseek-r1 配合 JSON 模式报 500

JSON 结构化输出建议使用 `qwen2.5:3b` 等普通对话模型。

### 召回不到历史记忆

检查三个点：

1. `.env` 里的 `EMBEDDING_MODEL` 是否正确；
2. `memory_store/` 是否已经生成并且有对应分支的数据；
3. 查询是否带了分支编号，例如：`r1 以前对气候影响的总结是什么？`

### 为什么不同主题曾经共用一个 r1

旧版本的编号是“当前 branches 表里最大编号 + 1”。如果中途删除过 `branches.sqlite`，或者在不同工作目录运行过 main，编号会从 r1 重新开始；而 `memory_store/` 是追加式的，旧 r1 记忆仍然保留。

当前版本已经修复：

- 主题按 `topic_key` 查重；
- 编号计数器持久化；
- `main.py` 的数据库路径固定到项目根目录。

## 当前阶段说明

- Trace + Eval 已完成：每次运行写入 `runs/*.jsonl`，`eval_research.py` 负责回归；
- 对话理解、代词消解和歧义澄清已完成代码接入；
- FastAPI 后端接口已经完成设计（`/chat`、`/chat/stream`、`/branches` 等），但代码尚未加入项目；
- 下一步建议先补连续对话评测，再考虑把 FastAPI 后端落地。

## 参考

- [langchain-ai/local-deep-researcher](https://github.com/langchain-ai/local-deep-researcher)
- [SWE-agent](https://github.com/SWE-agent/SWE-agent)：工具运行时、历史处理器、轨迹记录的设计参考
- [CrewAI RAGStorage](https://github.com/crewAIInc/crewAI/blob/main/lib/crewai/src/crewai/memory/storage/rag_storage.py)：RAG 记忆层设计参考
- [LangGraph](https://github.com/langchain-ai/langgraph)
- [Chroma](https://github.com/chroma-core/chroma)
