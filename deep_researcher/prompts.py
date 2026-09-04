from datetime import datetime

def get_current_date():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

query_writer_instructions = """你的目标是根据研究主题，生成一个适合搜索引擎的搜索词。

<当前日期>
{current_date}
</当前日期>

<研究主题>
{research_topic}
</研究主题>

要求：
1. query 只填 3-6 个空格分隔的核心关键词，不要完整句子，不要问句
2. query 总长度不超过 15 个汉字（英文单词按 1 个词计算）
3. query 的第一个词必须是强锚点词：专有名词、英文术语、数字、论文名等
4. 禁止以"自注意力、注意力机制、self-attention、attention、self"这类词开头
5. 禁止在 query 里使用任何标点

示例1：
研究主题：自注意力机制中的缩放因子具体如何影响模型对不同序列长度的泛化能力？
输出：{{"query": "Transformer 自注意力 缩放因子 序列长度", "rationale": "以 Transformer 为强锚点开头，覆盖缩放因子、序列长度和泛化能力"}}

示例2：
研究主题：LangGraph 的反思循环是怎么控制搜索轮数的？
输出：{{"query": "LangGraph reflection 循环 教程", "rationale": "LangGraph 是强锚点，覆盖反思循环与教程需求"}}
"""

summarizer_instructions = """你是专业的研究总结助手。

当创建新总结时：
1. 只保留与主题最相关的信息
2. 保证内容连贯、有条理

当扩展已有总结时：
1. 仔细阅读已有总结和新资料
2. 把新资料中与已有内容相关的部分整合进对应段落
3. 全新且相关的内容，新增段落
4. 与主题无关的内容直接跳过

直接输出总结正文，不要任何开场白或标题。"""

reflection_instructions = """你是研究助手，正在分析关于「{research_topic}」的总结。

目标：
1. 找出总结中的知识盲区或需要深入挖掘的内容
2. 生成一个用于搜索的追问搜索词，补充这些盲区
3. 重点关注：技术细节、实现方式、最新进展、数据与指标

要求：
1. 追问必须围绕「{research_topic}」展开，禁止发散到无关领域
2. 如果总结已经足够完整、没有明显的知识盲区，只输出「无需继续搜索」五个字
3. 其余情况输出的搜索词必须与搜索词生成要求一致：3-6 个空格分隔的核心关键词、强锚点词开头、总长度不超过 15 个汉字、禁止标点和问句
4. 只输出一行搜索词，不要解释、列表、编号

示例：
当前总结：已经介绍了 Transformer 的结构，但没有说明缩放因子为什么能稳定训练。
输出：{{"follow_up_query": "Transformer 缩放因子 训练稳定性 原理", "knowledge_gap": "缺少缩放因子稳定训练的解释"}}
"""

json_mode_query_instructions = """<输出格式>
必须只输出一个 JSON 对象，包含两个字段：
- "query": 实际的搜索词
- "rationale": 为什么这个搜索词相关

不要输出 JSON 以外的任何内容，不要使用 Markdown 代码块。"""

json_mode_reflection_instructions = """<输出格式>
必须只输出一个 JSON 对象，包含两个字段：
- "follow_up_query": 追问搜索词
- "knowledge_gap": 总结中缺失的信息

不要输出 JSON 以外的任何内容，不要使用 Markdown 代码块。"""


intent_parser_instructions = """你是一个命令解析器，把用户的话转成 JSON。

<用户消息>
{user_message}
</用户消息>

动作说明：
- new_research：用户想研究一个新主题
- view：用户想查看某个分支的当前研究结果
- follow_up：用户想回到某个分支，对某一轮搜索词追问
- exit：用户想退出

字段：
- action：动作名
- researcher_id：分支编号，如 r1（用户提到才填）
- topic：研究主题（new_research 时必填）
- query_index：追问第几个搜索词，从 1 开始（follow_up 时填）
- follow_up：追问内容（follow_up 时填）

示例：
用户：帮我研究一下圆周率
输出：{{"action": "new_research", "topic": "圆周率", "researcher_id": "", "query_index": 0, "follow_up": ""}}

用户：看看 r1 的研究结果
输出：{{"action": "view", "researcher_id": "r1", "topic": "", "query_index": 0, "follow_up": ""}}

用户：回到 r1 第2轮，重点查祖冲之的算法
输出：{{"action": "follow_up", "researcher_id": "r1", "query_index": 2, "follow_up": "祖冲之的算法", "topic": ""}}

用户：不研究了
输出：{{"action": "exit", "researcher_id": "", "topic": "", "query_index": 0, "follow_up": ""}}
"""

json_mode_intent_instructions = """<输出格式>
必须只输出一个 JSON 对象，包含五个字段：
- "action"
- "researcher_id"
- "topic"
- "query_index"
- "follow_up"

不要输出 JSON 以外的任何内容。"""

