from langchain_core.messages import SystemMessage, HumanMessage
from langchain_ollama import ChatOllama
from langgraph.constants import START, END
from langgraph.graph import StateGraph
import json
from pydantic import ValidationError
from .state import State
from .prompts import (
    get_current_date,
    query_writer_instructions,
    summarizer_instructions,
    reflection_instructions,
    json_mode_query_instructions,
    json_mode_reflection_instructions,
)
from .configuration import (
    MAX_LOOPS,
    QUERY_LLM,
    SUMMARIZE_LLM,
    REFLECT_LLM,
    SEARCH_MAX_RESULTS,
    SEARCH_KEEP_RESULTS,
    RELEVANCE_RATIO,
)
from .utils import is_valid_search_query
from .tools import WebResearchTools
from .schemas import Query, FollowUpQuery
from langgraph.checkpoint.sqlite import SqliteSaver
class DeepResearcher(StateGraph):
    """把整个研究流程封装成一个图类，节点都是类方法。"""

    def __init__(self):
        super().__init__(State)  #把State传给StateGraph
        self.summarize_llm = ChatOllama(model=SUMMARIZE_LLM, temperature=0)
        self.query_llm_json = ChatOllama(model=QUERY_LLM, temperature=0, format="json")
        self.reflect_llm_json = ChatOllama(model=REFLECT_LLM, temperature=0, format="json")
        self.tools = WebResearchTools(
            max_results=SEARCH_MAX_RESULTS,
            keep=SEARCH_KEEP_RESULTS,
            ratio=RELEVANCE_RATIO,
        )
        # 注册节点
        self.add_node("generate_query", self.generate_query)
        self.add_node("web_research", self.web_research)
        self.add_node("summarize_sources", self.summarize_sources)
        self.add_node("reflect_on_summary", self.reflect_on_summary)
        self.add_node("finalize_summary", self.finalize_summary)

        # 连接边
        self.add_edge(START, "generate_query")
        self.add_edge("generate_query", "web_research")
        self.add_edge("web_research", "summarize_sources")
        self.add_edge("summarize_sources", "reflect_on_summary")
        self.add_conditional_edges(
            "reflect_on_summary",
            self.route_research,
            {"web_research": "web_research", "finalize_summary": "finalize_summary"},
        )
        self.add_edge("finalize_summary", END)

    def generate_search_query_with_structured_output(
        self,
        llm,
        system_prompt: str,
        human_message: str,
        model_class,
        field_name: str,
        fallback: str,
    ) -> str:
        """用 JSON 模式让模型生成搜索词：解析 → pydantic 校验 → 内容校验 → 兜底。"""
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_message),
        ]
        response = llm.invoke(messages)

        query = ""
        import json
        try:
            data = json.loads(response.content)
            parsed = model_class.model_validate(data)
            query = getattr(parsed, field_name, "").strip()
        except (json.JSONDecodeError, ValidationError, AttributeError):
            query = ""

        if not is_valid_search_query(query):
            query = fallback
        return query

    def generate_query(self, state):
        formatted_prompt = (
            query_writer_instructions.format(
                current_date=get_current_date(),
                research_topic=state.research_topic,
            )
            + json_mode_query_instructions
        )
        query = self.generate_search_query_with_structured_output(
            llm=self.query_llm_json,
            system_prompt=formatted_prompt,
            human_message="请根据研究主题生成搜索词：",
            model_class=Query,
            field_name="query",
            fallback=f"Tell me more about {state.research_topic}",
        )
        return {
            "search_query": query,
            "search_query_history": [query],
        }

    def web_research(self, state):
        # print(f"本轮搜索词: {state.search_query}")
        results = self.tools.search(state.search_query)
        results = self.tools.filter_relevant(results, state.research_topic)
        lines = []
        source_lines = []
        for r in results:
            title = r["title"]
            url = r["url"]
            body = r["body"]
            lines.append(f"标题: {title}\n内容: {body}")
            source_lines.append(f"* {title} : {url}")

        return {
            "search_results": "\n\n".join(lines),
            "sources_gathered": source_lines,
            "searched_queries": [state.search_query],
            "research_loop_count": state.research_loop_count + 1,
        }

    def summarize_sources(self, state):
        if state.summary:
            human = (
                f"<已有总结>\n{state.summary}\n</已有总结>\n\n"
                f"<新资料>\n{state.search_results}\n</新资料>\n\n"
                f"请把新资料整合进已有总结（主题：{state.research_topic}）"
            )
        else:
            human = (
                f"<资料>\n{state.search_results}\n</资料>\n\n"
                f"请根据资料创建总结（主题：{state.research_topic}）"
            )
        response = self.summarize_llm.invoke([
            SystemMessage(content=summarizer_instructions),
            HumanMessage(content=human),
        ])
        return {"summary": response.content}

    def reflect_on_summary(self, state):
        formatted_prompt = (
            reflection_instructions.format(
                research_topic=state.research_topic
            )
            + json_mode_reflection_instructions
        )
        new_query = self.generate_search_query_with_structured_output(
            llm=self.reflect_llm_json,
            system_prompt=formatted_prompt,
            human_message=(
                f"当前总结如下：\n{state.summary}\n\n"
                f"已经搜索过的词：{state.search_query_history}\n"
                f"请分析知识盲区并生成追问搜索词。"
            ),
            model_class=FollowUpQuery,
            field_name="follow_up_query",
            fallback=f"Tell me more about {state.research_topic}",
        )

        if "无需继续搜索" in new_query:
            new_query = "无需继续搜索"

        return {
            "search_query": new_query,
            "search_query_history": [new_query],
        }

    def route_research(self, state):
        duplicate = state.search_query_history.count(state.search_query) > 1
        if (
            state.research_loop_count < MAX_LOOPS
            and state.search_query != "无需继续搜索"
            and not duplicate
        ):
            return "web_research"
        return "finalize_summary"

    def finalize_summary(self, state):
        all_sources = self.tools.deduplicate(state.sources_gathered)
        final = f"## 总结\n{state.summary}\n\n### 参考来源\n{all_sources}"
        return {"summary": final}

    @classmethod
    def build(cls, checkpointer=None):
        """组装并编译图，外部统一从这里拿实例。"""
        return cls().compile(checkpointer=checkpointer)


# if __name__ == "__main__":
#     topic=input('请输入研究主题:').strip()
#     if not topic:
#         print("研究主题不能为空。")
#         exit(1)
#     graph = DeepResearcher.build()
#     result=graph.invoke({'research_topic': topic})
#     print(result['summary'])
#     print(f"\n共研究 {result['research_loop_count']} 轮，收集 {len(result['sources_gathered'])} 条来源")


