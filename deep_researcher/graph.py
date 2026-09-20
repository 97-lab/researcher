from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.constants import END, START
from langgraph.graph import StateGraph

from .configuration import MAX_LOOPS, MAX_REVIEW_ROUNDS
from .context import (
    ContextBuilder,
    LastNObservations,
    TruncateEachObservation,
)
from .model_router import ModelRouter
from .prompts import (
    get_current_date,
    json_mode_query_instructions,
    json_mode_reflection_instructions,
    planner_instructions,
    query_writer_instructions,
    reflection_instructions,
    summarizer_instructions,
    reviewer_instructions,
)


from .schemas import FollowUpQuery, Query, ResearchPlan, ReviewResult
from .state import State
from .tool_registry import ToolError
from .tool_specs import build_default_registry
from .trace import trace_node
from .utils import deduplicate_sources, is_valid_search_query

class DeepResearcher(StateGraph):
    """把整个研究流程封装成一个图类，节点都是类方法。"""

    def __init__(self, tool_registry=None, model_router=None):
        super().__init__(State)
        self.model_router = model_router or ModelRouter()


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
        self.summarize_llm = self.model_router.get("summarize")
        self.add_node("plan_research", self.plan_research)
        self.add_node("recall_history", self.recall_history)
        self.add_node("generate_query", self.generate_query)
        self.add_node("web_research", self.web_research)
        self.add_node("summarize_sources", self.summarize_sources)
        self.add_node("reflect_on_summary", self.reflect_on_summary)
        self.add_node("review_report", self.review_report)
        self.add_node("finalize_summary", self.finalize_summary)

        self.add_edge(START, "plan_research")
        self.add_edge("plan_research", "recall_history")
        self.add_edge("recall_history", "generate_query")
        self.add_edge("generate_query", "web_research")
        self.add_edge("web_research", "summarize_sources")
        self.add_edge("summarize_sources", "reflect_on_summary")

        self.add_conditional_edges(
            "reflect_on_summary",
            self.route_research,
            {
                "web_research": "web_research",
                "review_report": "review_report",
            },
        )
        self.add_conditional_edges(
            "review_report",
            self.route_after_review,
            {
                "web_research": "web_research",
                "finalize_summary": "finalize_summary",
            },
        )
        self.add_edge("finalize_summary", END)
    def generate_search_query_with_structured_output(
            self,
            role: str,
            system_prompt: str,
            human_message: str,
            model_class,
            field_name: str,
            fallback: str,
    ) -> str:
        """用 JSON 模式生成结构化内容：路由模型 → 解析校验 → 重试 → 兜底。"""
        parsed, raw_text = self.model_router.invoke_json(
            role=role,
            system_prompt=system_prompt,
            human_prompt=human_message,
            model_class=model_class,
        )

        if parsed is None:
            return fallback

        value = getattr(parsed, field_name, "").strip()

        if not is_valid_search_query(value):
            return fallback

        return value
    @trace_node("plan_research")
    def plan_research(self, state):
        """规划者 Agent：先生成研究简报和子问题。"""
        system_prompt = planner_instructions.format(
            research_topic=state.research_topic
        )
        human_prompt = (
            f"研究主题：{state.research_topic}\n"
            f"请生成研究简报和子问题。"
        )

        parsed, raw_text = self.model_router.invoke_json(
            role="planner",
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            model_class=ResearchPlan,
        )

        if parsed is None:
            return {
                "research_brief": f"研究主题：{state.research_topic}",
                "sub_questions": [],
            }

        brief = parsed.brief.strip() or state.research_topic
        sub_questions = []
        for question in parsed.sub_questions:
            cleaned = question.strip()
            if cleaned:
                sub_questions.append(cleaned)

        return {
            "research_brief": brief,
            "sub_questions": sub_questions,
        }


    @trace_node("recall_history")
    def recall_history(self, state):
        """研究开始前，先从 RAG 里召回相关历史记忆。"""
        try:
            observation = self.tool_registry.call(
                "recall_memory",
                query=state.research_topic,
                researcher_id=state.researcher_id,
                thread_id=state.thread_id,
                limit=3,
            )
        except ToolError as exc:
            return {"memory_hits": []}

        hits = observation["hits"]
        memory_lines = []
        for hit in hits:
            memory_lines.append(f"相关度 {hit['score']}：{hit['content']}")

        return {"memory_hits": memory_lines}

    @trace_node("generate_query")
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
            role="query",
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

    @trace_node("web_research")
    def web_research(self, state):
        try:
            observation = self.tool_registry.call(
                "web_search",
                query=state.search_query,
                topic=state.research_topic,
            )
        except ToolError as exc:
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


    @trace_node("summarize_sources")
    def summarize_sources(self, state):
        human = self.context_builder.build_summary_human(state)

        messages = [
            SystemMessage(content=summarizer_instructions),
            HumanMessage(content=human),
        ]

        pieces = []
        for chunk in self.summarize_llm.stream(messages):
            text = chunk.content if chunk.content else ""
            pieces.append(text)

        return {"summary": "".join(pieces)}
    @trace_node("reflect_on_summary")
    def reflect_on_summary(self, state):
        formatted_prompt = (
            reflection_instructions.format(
                research_topic=state.research_topic
            )
            + json_mode_reflection_instructions
        )

        human_message = self.context_builder.build_reflection_human(state)

        new_query = self.generate_search_query_with_structured_output(
            role="reflect",
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
        # 研究员认为可以收尾时，先交给审核者检查
        return "review_report"
    @trace_node("review_report")
    def review_report(self, state):
        """审核者 Agent：检查子问题覆盖度，必要时给出补搜词。"""
        human_message = self.context_builder.build_review_human(state)

        parsed, raw_text = self.model_router.invoke_json(
            role="reviewer",
            system_prompt=reviewer_instructions,
            human_prompt=human_message,
            model_class=ReviewResult,
        )

        if parsed is None:
            return {
                "review_passed": True,
                "review_feedback": "审核输出失败，直接收尾。",
                "uncovered_questions": [],
            }

        uncovered_questions = []
        for item in parsed.uncovered_questions:
            text = str(item).strip()
            if not text:
                continue

            if text.isdigit():
                index = int(text)
                if 1 <= index <= len(state.sub_questions):
                    uncovered_questions.append(
                        state.sub_questions[index - 1]
                    )
                continue

            uncovered_questions.append(text)

        review_passed = parsed.passed
        if not review_passed and not uncovered_questions:
            review_passed = True

        if review_passed:
            uncovered_questions = []

        next_query = parsed.next_query.strip()

        return {
            "review_passed": review_passed,
            "review_feedback": parsed.feedback,
            "uncovered_questions": uncovered_questions,
            "search_query": next_query or state.search_query,
            "search_query_history": [next_query] if next_query else [],
            "review_round": state.review_round + 1,
        }

    def route_after_review(self, state):
        """审核后决定：补搜一次，还是收尾。"""
        if state.review_passed:
            return "finalize_summary"

        if state.review_round > MAX_REVIEW_ROUNDS:
            return "finalize_summary"

        if not state.search_query or state.search_query == "无需继续搜索":
            return "finalize_summary"

        duplicate = state.search_query_history.count(state.search_query) > 1
        if duplicate:
            return "finalize_summary"

        return "web_research"

    def finalize_summary(self, state):
        all_sources = deduplicate_sources(state.sources_gathered)
        final = f"## 总结\n{state.summary}\n\n### 参考来源\n{all_sources}"

        if state.review_feedback and not state.review_passed:
            final += f"\n\n### 审核意见\n{state.review_feedback}"

            if state.uncovered_questions:
                question_lines = []
                for question in state.uncovered_questions:
                    question_lines.append(f"- {question}")
                final += (
                        "\n\n未完全覆盖的子问题：\n"
                        + "\n".join(question_lines)
                )

        return {"summary": final}

    @classmethod
    def build(cls, checkpointer=None, tool_registry=None, model_router=None):
        """组装并编译图，外部统一从这里拿实例。"""
        return cls(
            tool_registry=tool_registry,
            model_router=model_router,
        ).compile(checkpointer=checkpointer)
