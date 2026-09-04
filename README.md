# 本地深度研究员（Local Deep Researcher 复刻版）

输入一个研究主题，程序会自动帮你：搜索资料 → 阅读并总结 → 反思还有哪里没讲清楚 → 再搜再总结 → 最后产出一份带参考来源的研究报告。

## 它能做什么

- 你输入：`讲解一下圆周率`
- 它输出：一份关于圆周率的总结报告，后面跟着它用过的参考来源链接

整个过程中，它最多会搜索 3 轮，每轮都会根据“上一轮还缺什么”自动换一个搜索方向。

## 技术栈（大白话版）

| 组件 | 作用 |
|---|---|
| Python | 写程序的语言 |
| LangGraph | 把“搜索→总结→反思→再搜索”组织成一个流程图 |
| Ollama + deepseek-r1:8b | 本地跑的大模型，负责生成搜索词、总结、反思 |
| Tavily / Bing | 搜索引擎，负责找资料 |

## 怎么跑起来

1. 安装 Python 3.11 以上版本
2. 安装依赖：
   ```
   pip install -r requirements.txt
   ```
3. 配置环境（二选一）：
   - 用 Tavily（推荐）：注册 https://tavily.com 拿到 key，在 `.env` 里写 `SEARCH_API=tavily` 和 `TAVILY_API_KEY=你的key`；更安全的做法是把 key 设成系统环境变量，别放进项目文件
   - 用 Bing：把 `.env` 里 `SEARCH_API` 改成 `bing`（不需要 key，但搜索结果质量差一些）
4. 运行：
   ```
   python graph.py
   ```
5. 输入研究主题，回车，等它跑完。

## 项目文件都是干嘛的

| 文件 | 作用 |
|---|---|
| graph.py | 主程序：流程图和所有节点 |
| state.py | 状态：整个流程中要传递的数据 |
| prompts.py | 提示词：教模型怎么生成搜索词、总结、反思 |
| schemas.py | 数据契约：规定模型必须输出什么样的 JSON |
| tools.py | 工具：搜索（Tavily/Bing）、相关性过滤、去重 |
| utils.py | 小工具函数 |
| configuration.py | 配置：读 .env 里的设置 |

## 常见问题

- 报错 `缺少 TAVILY_API_KEY`：说明 key 没配好
- 报错 `401`：key 填错了
- 模型找不到：先在 Ollama 里执行 `ollama pull deepseek-r1:8b`
- 想换回 Bing：把 `.env` 里 `SEARCH_API` 改成 `bing`

## 提醒

`.env` 里有敏感信息（API key），不要提交到 GitHub，用 `.gitignore` 忽略它。
