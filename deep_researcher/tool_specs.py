from __future__ import annotations

from pydantic import BaseModel, Field

from .configuration import RELEVANCE_RATIO, SEARCH_KEEP_RESULTS, SEARCH_MAX_RESULTS
from .memory import DEFAULT_MIN_SCORE, MemoryStore
from .tool_registry import ToolRegistry, ToolSpec
from .tools import WebResearchTools

class WebSearchParams(BaseModel):
    """web_search 工具的参数。"""

    query: str=Field(min_length=1, description="要搜索的关键词")
    topic:str=Field(min_length=1, description="研究主题，用于过滤无关结果")

class RecallMemoryParams(BaseModel):
    """recall_memory 工具的参数。"""
    query: str = Field(min_length=1, description="要回忆的问题")
    researcher_id: str = Field(
        default="",
        description="分支编号，如 r1；空字符串表示搜索所有分支",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="最多返回多少条历史记忆",
    )
    min_score: float = Field(
        default=DEFAULT_MIN_SCORE,
        ge=0.0,
        le=1.0,
        description="相关度门槛，低于该值的历史版本会被过滤",
    )

def _build_web_search_handler(web_tools: WebResearchTools):
    """把 WebResearchTools 包装成统一工具接口。"""

    def web_search(query: str, topic: str) -> dict:
        raw_results = web_tools.search(query)
        filtered_results = web_tools.filter_relevant(raw_results, topic)

        content_lines = []
        source_lines = []
        for item in filtered_results:
            content_lines.append(
                f"标题: {item['title']}\n内容: {item['body']}"
            )
            source_lines.append(
                f"* {item['title']} : {item['url']}"
            )

        return {
            "query": query,
            "results": filtered_results,
            "content": "\n\n".join(content_lines),
            "sources": source_lines,
            "raw_count": len(raw_results),
            "kept_count": len(filtered_results),
        }

    return web_search


def _build_recall_memory_handler(memory: MemoryStore):
    """把 MemoryStore.recall 包装成统一工具接口。"""

    def recall_memory(
        query: str,
        researcher_id: str = "",
        limit: int = 5,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> dict:
        hits = memory.recall(
            query=query,
            researcher_id=researcher_id,
            limit=limit,
            min_score=min_score,
        )
        return {
            "query": query,
            "hits": hits,
            "count": len(hits),
        }

    return recall_memory


def build_default_registry(memory: MemoryStore | None = None) -> ToolRegistry:
    """组装本项目的默认工具集。

      memory 为 None 时只注册搜索工具，方便独立测试图。
      memory 不为 None 时额外注册 recall_memory。
      """
    web_tools = WebResearchTools(
        max_results=SEARCH_MAX_RESULTS,
        keep=SEARCH_KEEP_RESULTS,
        ratio=RELEVANCE_RATIO,
    )
    registry = ToolRegistry()

    registry.register(
        ToolSpec(
            name="web_search",
            description="用搜索引擎查找资料，过滤无关结果，返回统一格式的搜索观察。",
            parameters=WebSearchParams,
            handler=_build_web_search_handler(web_tools),
            permission="network",
        )
    )

    if memory is not None:
        registry.register(
            ToolSpec(
                name="recall_memory",
                description="从 RAG 历史版本库中召回与问题相关的旧研究总结。",
                parameters=RecallMemoryParams,
                handler=_build_recall_memory_handler(memory),
                permission="safe",
            )
        )

    return registry








