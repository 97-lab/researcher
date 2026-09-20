import operator
from dataclasses import dataclass, field

from typing_extensions import Annotated


@dataclass
class State:
    research_topic: str
    researcher_id: str = ""
    thread_id: str = ""
    search_query: str = ""
    search_results: str = ""
    summary: str = ""
    research_brief: str = ""  # 规划者生成的研究简报与子问题
    sub_questions: list = field(default_factory=list)  # 规划者生成的研究简报与子问题


    # 审核者 Agent 的状态
    review_round: int = 0
    review_passed: bool = False
    review_feedback: str = ""
    uncovered_questions: list = field(default_factory=list)


    # 记录已经研究了几轮，循环靠它判断什么时候停
    research_loop_count: int = 0

    # 收集所有来源，最后写进报告
    sources_gathered: Annotated[list, operator.add] = field(
        default_factory=list
    )
    search_query_history: Annotated[list, operator.add] = field(
        default_factory=list
    )

    # 只记录真正搜过的搜索词
    searched_queries: Annotated[list, operator.add] = field(
        default_factory=list
    )

    # 每一轮搜索的完整观察，供 HistoryProcessor 裁剪
    search_observations: Annotated[list, operator.add] = field(
        default_factory=list
    )

    # RAG 召回的历史记忆，供 ContextBuilder 注入提示词
    memory_hits: Annotated[list, operator.add] = field(
        default_factory=list
    )
