from __future__ import annotations

from .configuration import (
    CONTEXT_KEEP_LAST_OBSERVATIONS,
    CONTEXT_MAX_MEMORY_CHARS,
    CONTEXT_MAX_OBSERVATION_CHARS,
)



class HistoryProcessor:
    """历史处理器基类：输入一组历史文本，输出处理后的历史文本。"""

    def __call__(self, history: list[str]) -> list[str]:
        raise NotImplementedError

class LastNObservations(HistoryProcessor):
    """只保留最近 N 条搜索观察。

    这对应 SWE-agent 里的 LastNObservations：
    旧观察不是永远要带着，模型只需要看最近几轮。
    """

    def __init__(self, n: int = CONTEXT_KEEP_LAST_OBSERVATIONS):
        if n < 1:
            raise ValueError("n 必须大于等于 1")
        self.n = n

    def __call__(self, history: list[str]) -> list[str]:
        if not history:
            return []
        return history[-self.n :]

class TruncateEachObservation(HistoryProcessor):
    """把每条观察截断到最大长度。

    对应 SWE-agent 里对历史内容做裁剪的思想：
    单条搜索结果可能非常长，不能整条塞进 prompt。
    """

    def __init__(self, max_chars: int = CONTEXT_MAX_OBSERVATION_CHARS):
        if max_chars < 1:
            raise ValueError("max_chars 必须大于等于 1")
        self.max_chars = max_chars

    def __call__(self, history: list[str]) -> list[str]:
        processed = []
        for item in history:
            if len(item) <= self.max_chars:
                processed.append(item)
            else:
                processed.append(
                    item[: self.max_chars] + "\n\n[该条资料过长，已截断]"
                )
        return processed


class ContextBuilder:
    """把分散的状态拼成模型可读的上下文。"""

    def __init__(
        self,
        history_processors=None,
        max_memory_chars: int = CONTEXT_MAX_MEMORY_CHARS,
    ):
        if history_processors is None:
            history_processors = [
                LastNObservations(),
                TruncateEachObservation(),
            ]
        self.history_processors = history_processors
        self.max_memory_chars = max_memory_chars

    def _process_observations(self, observations: list[str]) -> list[str]:
        """按顺序执行所有历史处理器。"""
        processed = list(observations)
        for processor in self.history_processors:
            processed = processor(processed)
        return processed

    def build_observation_text(self, observations: list[str]) -> str:
        """把搜索观察拼成一段文字。"""
        processed = self._process_observations(observations)
        if not processed:
            return "（暂无搜索资料）"
        return "\n\n--- 新一轮搜索 ---\n\n".join(processed)

    def build_memory_text(self, memory_hits: list[str]) -> str:
        """把 RAG 召回的历史记忆拼成一段文字。"""
        if not memory_hits:
            return "（没有找到相关的历史记忆）"

        text = "\n\n".join(memory_hits)
        if len(text) > self.max_memory_chars:
            text = text[: self.max_memory_chars] + "\n\n[历史记忆过长，已截断]"
        return text


    def build_brief_text(self, state) -> str:
        """把研究简报和子问题拼成一段文字。"""
        brief = getattr(state, "research_brief", "") or "（暂无研究简报）"
        sub_questions = getattr(state, "sub_questions", []) or []

        if sub_questions:
            question_lines = []
            for index, question in enumerate(sub_questions, 1):
                question_lines.append(f"{index}. {question}")
            question_text = "\n".join(question_lines)
        else:
            question_text = "（暂无子问题）"

        return (
            f"<研究简报>\n{brief}\n</研究简报>\n\n"
            f"<子问题>\n{question_text}\n</子问题>"
        )

    def build_summary_human(self, state) -> str:
        """构建“总结节点”要发给模型的用户消息。"""
        observation_text = self.build_observation_text(
            state.search_observations
        )
        memory_text = self.build_memory_text(state.memory_hits)
        brief_text = self.build_brief_text(state)
        if state.summary:
            return (
                f"{brief_text}\n\n"
                f"<已有总结>\n{state.summary}\n</已有总结>\n\n"
                f"<相关历史记忆>\n{memory_text}\n</相关历史记忆>\n\n"
                f"<近期搜索资料>\n{observation_text}\n</近期搜索资料>\n\n"
                f"请把新资料整合进已有总结（主题：{state.research_topic}）。\n"
                f"总结时要逐一覆盖上面的子问题。\n"
                f"历史记忆只作为背景参考，不要把它当成新的参考来源。"
            )
        return (
            f"{brief_text}\n\n"
            f"<相关历史记忆>\n{memory_text}\n</相关历史记忆>\n\n"
            f"<搜索资料>\n{observation_text}\n</搜索资料>\n\n"
            f"请根据资料创建总结（主题：{state.research_topic}）。\n"
            f"总结时要逐一覆盖上面的子问题。\n"
            f"历史记忆只作为背景参考，不要把它当成新的参考来源。"
        )

    def build_query_human(self, state) -> str:
        """构建“生成搜索词节点”要发给模型的用户消息。"""
        memory_text = self.build_memory_text(state.memory_hits)
        brief_text = self.build_brief_text(state)

        return (
            f"请根据研究简报生成搜索词。\n\n"
            f"{brief_text}\n\n"
            f"<相关历史记忆>\n{memory_text}\n</相关历史记忆>\n\n"
            f"如果历史记忆已经覆盖了某个方向，请换一个新的搜索角度。"
        )

    def build_reflection_human(self, state) -> str:
        """构建“反思节点”要发给模型的用户消息。"""
        memory_text = self.build_memory_text(state.memory_hits)
        brief_text = self.build_brief_text(state)

        return (
            f"{brief_text}\n\n"
            f"当前总结如下：\n{state.summary}\n\n"
            f"已经搜索过的词：{state.search_query_history}\n"
            f"<相关历史记忆>\n{memory_text}\n</相关历史记忆>\n\n"
            f"请检查哪些子问题还没有被充分回答，并生成追问搜索词。"
        )


