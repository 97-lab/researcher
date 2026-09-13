import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from deep_researcher.context import (
    ContextBuilder,
    LastNObservations,
    TruncateEachObservation,
)
from deep_researcher.state import State


def main():
    state = State(
        research_topic="北极圈的气候影响",
        researcher_id="r1",
        summary="",
        search_observations=[
            "第一轮搜索资料：北极圈温度上升。",
            "第二轮搜索资料：北极圈海冰减少。",
            "第三轮搜索资料：北极圈冻土融化。",
        ],
        memory_hits=[
            "相关度 0.51：研究主题：北极圈\n总结：旧版本说北极圈升温速度是全球两倍。",
        ],
    )

    builder = ContextBuilder(
        history_processors=[
            LastNObservations(2),
            TruncateEachObservation(max_chars=10)        ],

        max_memory_chars=500,
    )

    context = builder.build_summary_human(state)
    print(context)

    assert "第二轮" in context
    assert "第三轮" in context
    assert "第一轮" not in context
    assert "旧版本说北极圈升温速度" in context
    assert "已截断" in context

    print("\n测试通过：只保留最近 2 条、超长内容被截断、历史记忆被注入。")


if __name__ == "__main__":
    main()