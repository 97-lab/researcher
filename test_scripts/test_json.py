import json
from langchain_ollama import ChatOllama


llm = ChatOllama(model="deepseek-r1:8b", temperature=0, format="json")

prompt = """你是一个搜索词生成器。根据下面的研究主题，生成一个适合搜索引擎的搜索词。

研究主题：自注意力机制中的缩放因子具体如何影响模型对不同序列长度的泛化能力？

请严格输出 JSON，格式如下：
{"query": "实际的搜索词", "rationale": "为什么这个搜索词相关"}

不要输出 JSON 以外的任何内容。"""

response = llm.invoke(prompt)
print("原始输出:")
print(response.content)
print("-" * 40)
try:
    data = json.loads(response.content)
    print("解析成功:", data)
    print("query:", data["query"])
    print("rationale:", data["rationale"])
except Exception as e:
    print("解析失败:", type(e).__name__, str(e))