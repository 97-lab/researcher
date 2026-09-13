import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from pydantic import ValidationError

from .configuration import MAX_LOOPS, QUERY_LLM, REFLECT_LLM, SUMMARIZE_LLM
from .context import (
    ContextBuilder,
    LastNObservations,
    TruncateEachObservation,
)
from .prompts import (
    get_current_date,
    json_mode_query_instructions,
    json_mode_reflection_instructions,
    query_writer_instructions,
    reflection_instructions,
    summarizer_instructions,
)
from .schemas import FollowUpQuery, Query
from .state import State
from .tool_registry import ToolError
from .tool_specs import build_default_registry
from .utils import deduplicate_sources, is_valid_search_query


class DeepResearcher(StateGraph):
    """把整个研究流程封装成一个图类，节点都是类方法。"""

    def __init__(self, tool_registry=None):
        super().__init__(State)

        # 工具注册表由外部注入；不传就只注册 web_search
        if tool_registry is None:
            self.tool_registry = build_default_registry()
        else:
            self.tool_registry = tool_registry

        self.context_builder = ContextBuilder(
            history_processors=[
                LastNObservations(),
                TruncateEachObservation(),
            ]
        )

        self.summarize_llm = ChatOllama(
            model=SUMMARIZE_LLM,
            temperature=0,
        )
        self.query_llm_json = ChatOllama(
            model=QUERY_LLM,
            temperature=0,
            format="json",
        )
        self.reflect_llm_json = ChatOllama(
            model=REFLECT_LLM,
            temperature=0,
            format="json",
        )

        self.add_node("recall_history", self.recall_history)
        self.add_node("generate_query", self.generate_query)
        self.add_node("web_research", self.web_research)
        self.add_node("summarize_sources", self.summarize_sources)
        self.add_node("reflect_on_summary", self.reflect_on_summary)
        self.add_node("finalize_summary", self.finalize_summary)

        self.add_edge(START, "recall_history")
        self.add_edge("recall_history", "generate_query")
        self.add_edge("generate_query", "web_research")
        self.add_edge("web_research", "summarize_sources")
        self.add_edge("summarize_sources", "reflect_on_summary")
        self.add_conditional_edges(
            "reflect_on_summary",
            self.route_research,
            {
                "web_research": "web_research",
                "finalize_summary": "finalize_summary",
            },
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
        """用 JSON 模式生成搜索词：解析 → Pydantic 校验 → 内容校验 → 兜底。"""
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_message),
        ]
        response = llm.invoke(messages)

        query = ""
        try:
            data = json.loads(response.content)
            parsed = model_class.model_validate(data)
            query = getattr(parsed, field_name, "").strip()
        except (json.JSONDecodeError, ValidationError, AttributeError):
            query = ""

        if not is_valid_search_query(query):
            query = fallback

        return query

    def recall_history(self, state):
        """研究开始前，先从 RAG 里召回相关历史记忆。"""
        try:
            observation = self.tool_registry.call(
                "recall_memory",
                query=state.research_topic,
                researcher_id=state.researcher_id,
                limit=3,
            )
        except ToolError as exc:
            print(f"[recall_history] 历史记忆检索失败：{exc}")
            return {"memory_hits": []}

        hits = observation["hits"]
        memory_lines = []
        for hit in hits:
            memory_lines.append(f"相关度 {hit['score']}：{hit['content']}")

        print(f"[recall_history] 命中 {len(memory_lines)} 条历史记忆")
        return {"memory_hits": memory_lines}

    def generate_query(self, state):
        formatted_prompt = (
            query_writer_instructions.format(
                current_date=get_current_date(),
                research_topic=state.research_topic,
            )
            + json_mode_query_instructions
        )

        human_message = self.context_builder.build_query_human(state)

        query = self.generate_search_query_with_structured_output(
            llm=self.query_llm_json,
            system_prompt=formatted_prompt,
            human_message=human_message,
            model_class=Query,
            field_name="query",
            fallback=f"Tell me more about {state.research_topic}",
        )

        return {
            "search_query": query,
            "search_query_history": [query],
        }

    def web_research(self, state):
        try:
            observation = self.tool_registry.call(
                "web_search",
                query=state.search_query,
                topic=state.research_topic,
            )
        except ToolError as exc:
            print(f"[web_research] 搜索失败：{exc}")
            return {
                "search_results": f"搜索失败：{exc}",
                "sources_gathered": [],
                "searched_queries": [state.search_query],
                "search_observations": [],
                "research_loop_count": state.research_loop_count + 1,
            }

        return {
            "search_results": observation["content"],
            "sources_gathered": observation["sources"],
            "searched_queries": [state.search_query],
            "search_observations": [observation["content"]],
            "research_loop_count": state.research_loop_count + 1,
        }

    def summarize_sources(self, state):
        human = self.context_builder.build_summary_human(state)

        messages = [
            SystemMessage(content=summarizer_instructions),
            HumanMessage(content=human),
        ]

        print("\n[模型生成中]\n", flush=True)

        pieces = []
        for chunk in self.summarize_llm.stream(messages):
            text = chunk.content if chunk.content else ""
            print(text, end="", flush=True)
            pieces.append(text)

        print("\n", flush=True)

        return {"summary": "".join(pieces)}

    def reflect_on_summary(self, state):
        formatted_prompt = (
            reflection_instructions.format(
                research_topic=state.research_topic
            )
            + json_mode_reflection_instructions
        )

        human_message = self.context_builder.build_reflection_human(state)

        new_query = self.generate_search_query_with_structured_output(
            llm=self.reflect_llm_json,
            system_prompt=formatted_prompt,
            human_message=human_message,
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
        all_sources = deduplicate_sources(state.sources_gathered)
        final = f"## 总结\n{state.summary}\n\n### 参考来源\n{all_sources}"
        return {"summary": final}

    @classmethod
    def build(cls, checkpointer=None, tool_registry=None):
        """组装并编译图，外部统一从这里拿实例。"""
        return cls(tool_registry=tool_registry).compile(
            checkpointer=checkpointer
        )