# 本地深度研究员（Local Deep Researcher 复刻版）

一个完全本地运行的深度研究助手：输入一句话，它会自动搜索资料、阅读总结、反思盲区、继续追问，最后产出一份带参考来源的研究报告。

本项目从 [langchain-ai/local-deep-researcher](https://github.com/langchain-ai/local-deep-researcher) 复刻并逐步改造，全部模型跑在本地 Ollama，不需要云端 API。

## 现在能做什么

- **自然语言交互**：直接说话，程序里的模型负责理解你的意图
- **自动研究**：生成搜索词 → 搜索 → 总结 → 反思 → 再搜，最多 3 轮
- **带引用的报告**：总结后面跟着用过的参考来源链接
- **分支管理**：每次研究是一个分支（r1、r2…），可以随时查看
- **追问重跑**：对分支的某一轮搜索词追问，程序会回到那一轮、换新词重新研究
- **时间旅行**：每一步状态自动存入 SQLite，可恢复到任意历史时间点
- **结构化输出**：模型必须填 JSON 字段，格式稳定，坏输出自动走兜底

## 技术栈

| 组件 | 作用 |
|---|---|
| Python + LangGraph | 把研究流程组织成状态图 |
| Ollama + deepseek-r1:8b | 本地推理模型：生成搜索词、总结、反思 |
| Ollama + qwen2.5:3b | 本地轻量模型：解析用户意图 |
| Tavily / Bing | 搜索引擎 |
| SQLite | checkpoint 时间旅行存档 + 分支登记表 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 `.env`

参考 `.env.example`，在项目根目录建 `.env`：

```ini
LOCAL_LLM=deepseek-r1:8b
INTENT_LLM=qwen2.5:3b
SEARCH_API=tavily
TAVILY_API_KEY=tvly-你的key
```

- 用 Tavily 搜索（推荐）：去 [tavily.com](https://tavily.com) 注册，把 key 填进 `TAVILY_API_KEY`；更安全的做法是设成系统环境变量
- 用 Bing 搜索：把 `SEARCH_API` 改成 `bing`（不需要 key）

### 3. 拉取本地模型

```bash
ollama pull deepseek-r1:8b
ollama pull qwen2.5:3b
```

### 4. 运行

```bash
python main.py
```

直接输入自然语言，例如：

```text
你想做什么？：帮我研究一下圆周率
（创建分支 r1，自动搜索、总结、反思，最后打印报告）

你想做什么？：看看 r1
（查看 r1 当前版本的搜索词和总结）

你想做什么？：回到 r1 第2轮，重点查祖冲之的算法
（回到 r1 的第 2 轮搜索前，换新词重跑后面的流程）

你想做什么？：退出
```

## 项目结构

```text
复刻1/
├── main.py                    # 程序入口：自然语言交互
├── branch_store.py            # 分支登记表（r1/r2… 当前版本）
├── deep_researcher/           # 核心代码包
│   ├── graph.py               # 研究流程图（DeepResearcher）
│   ├── state.py               # 流程状态
│   ├── schemas.py             # 结构化输出的数据契约
│   ├── prompts.py             # 提示词
│   ├── configuration.py       # 读取 .env 配置
│   ├── tools.py               # 搜索工具（Tavily / Bing）
│   └── utils.py               # 通用小工具
├── test_scripts/              # 测试脚本
├── .env.example               # 配置示例（可提交）
├── requirements.txt           # 依赖清单
└── README.md
```

## 数据文件说明

运行时会在项目根目录自动生成两个文件（已加入 `.gitignore`，不会上传）：

| 文件 | 作用 |
|---|---|
| `research.sqlite` | 每一步状态快照，时间旅行的存档 |
| `branches.sqlite` | 分支登记表，记录每个分支的当前版本 |

## 常见问题

- `WinError 10061 连接被拒绝`：Ollama 没启动，先打开 Ollama 应用
- `model not found`：模型没拉全，执行上面第 3 步
- 意图解析慢：把 `INTENT_LLM` 换成更小的模型
- Tavily 报 401：`TAVILY_API_KEY` 填错了

## 规划中

- RAG 记忆：让模型能“回忆”被覆盖掉的旧版本
- 多 Agent：把一个大主题拆成多个子主题并行研究
- LangGraph Studio 可视化运行

## 提醒

`.env` 里包含敏感信息（API key），已通过 `.gitignore` 忽略，请勿提交到 GitHub。
