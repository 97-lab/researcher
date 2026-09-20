import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import BaseModel, Field

from branch_store import BranchStore
from deep_researcher.context import (
    ContextBuilder,
    LastNObservations,
    TruncateEachObservation,
)
from deep_researcher.memory import distance_to_score
from deep_researcher.schemas import ResearchPlan, ReviewResult, UserIntent
from deep_researcher.state import State
from deep_researcher.tool_registry import (
    ToolError,
    ToolRegistry,
    ToolSpec,
)
from deep_researcher.trace import (
    TraceRecorder,
    record_event,
    use_recorder,
)
from deep_researcher.model_router import ModelRouter

class EchoParams(BaseModel):
    text: str = Field(min_length=1)


def echo(text: str) -> dict:
    return {"echo": text}


def check_context():
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
            "相关度 0.51：旧版本说北极圈升温速度是全球两倍。",
        ],
    )

    builder = ContextBuilder(
        history_processors=[
            LastNObservations(2),
            TruncateEachObservation(max_chars=10),
        ],
        max_memory_chars=500,
    )

    text = builder.build_summary_human(state)

    assert "第二轮" in text
    assert "第三轮" in text
    assert "第一轮" not in text
    assert "旧版本说北极圈升温速度" in text
    assert "已截断" in text


def check_tool_registry():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="echo",
            description="回显工具",
            parameters=EchoParams,
            handler=echo,
            permission="safe",
        )
    )

    assert registry.call("echo", text="你好") == {"echo": "你好"}

    try:
        registry.call("echo", text="")
    except ToolError:
        pass
    else:
        raise AssertionError("空字符串应该被参数校验拦截")

    try:
        registry.call("not_exists")
    except ToolError:
        pass
    else:
        raise AssertionError("不存在的工具应该被拦截")


def check_trace():
    temp_dir = Path(tempfile.mkdtemp(prefix="trace_eval_"))
    try:
        recorder = TraceRecorder.create(temp_dir, label="eval")

        with use_recorder(recorder):
            record_event("custom_event", value=1)

        recorder.finish(status="ok")

        lines = recorder.path.read_text(encoding="utf-8").strip().splitlines()
        events = [json.loads(line) for line in lines]
        names = [event["event"] for event in events]

        assert "run_start" in names
        assert "custom_event" in names
        assert "run_end" in names
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def check_branch_mapping():
    temp_dir = Path(tempfile.mkdtemp(prefix="branch_eval_"))
    try:
        store = BranchStore(str(temp_dir / "branches.sqlite"))

        first, created_first = store.get_or_create_by_topic("圆周率")
        second, created_second = store.get_or_create_by_topic("亚里士多德")
        again, created_again = store.get_or_create_by_topic(" 圆周率 ")

        assert created_first is True
        assert created_second is True
        assert created_again is False

        assert first["researcher_id"] == "r1"
        assert second["researcher_id"] == "r2"
        assert again["researcher_id"] == "r1"

        store.conn.close()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def check_memory_score():
    score = distance_to_score(1.1898634433746338)
    assert abs(score - 0.4050682783126831) < 0.001
    assert distance_to_score(0.0) == 1.0


def check_planner_context():
    plan = ResearchPlan.model_validate(
        {
            "brief": "搞清楚北极圈气候变化的成因和影响",
            "sub_questions": [
                "北极圈升温速度有多快？",
                "海冰减少有什么后果？",
            ],
        }
    )

    assert plan.brief
    assert len(plan.sub_questions) == 2

    state = State(
        research_topic="北极圈的气候影响",
        research_brief=plan.brief,
        sub_questions=plan.sub_questions,
    )

    builder = ContextBuilder()
    text = builder.build_query_human(state)

    assert "研究简报" in text
    assert "北极圈升温速度有多快" in text
    assert "海冰减少有什么后果" in text

def check_reviewer_context():
    review = ReviewResult.model_validate(
        {
            "passed": False,
            "feedback": "海冰减少的后果还没有明确结论。",
            "uncovered_questions": ["海冰减少有什么后果？"],
            "next_query": "北极圈 海冰 减少 后果",
        }
    )

    assert review.passed is False
    assert len(review.uncovered_questions) == 1

    state = State(
        research_topic="北极圈的气候影响",
        research_brief="搞清楚北极圈气候变化的成因和影响",
        sub_questions=[
            "北极圈升温速度有多快？",
            "海冰减少有什么后果？",
        ],
        summary="目前只说明了升温速度，还没有展开海冰后果。",
        search_query_history=["北极圈 气候变化 影响"],
    )

    builder = ContextBuilder()
    text = builder.build_review_human(state)

    assert "研究简报" in text
    assert "当前总结" in text
    assert "海冰减少有什么后果" in text


def main():
    checks = [
        ("上下文构建", check_context),
        ("工具注册表", check_tool_registry),
        ("轨迹记录", check_trace),
        ("主题与分支映射", check_branch_mapping),
        ("记忆相关度换算", check_memory_score),
        ("规划者上下文", check_planner_context),
        ("模型路由", check_model_router),
        ("JSON 自动重试", check_json_retry),
    ]

    passed = 0

    for name, func in checks:
        try:
            func()
        except Exception:
            print(f"[FAIL] {name}")
            traceback.print_exc()
        else:
            print(f"[PASS] {name}")
            passed += 1

    print(f"\n通过 {passed}/{len(checks)}")

    if passed != len(checks):
        sys.exit(1)
class Answer(BaseModel):
    value: str


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)

    def invoke(self, messages):
        return FakeResponse(self.responses.pop(0))


def check_model_router():
    router = ModelRouter(
        routes={"intent": "qwen2.5:3b", "default": "qwen2.5:3b"},
        client_factory=lambda **kwargs: FakeLLM(['{"value": "ok"}']),
    )

    assert router.model_name_for("intent") == "qwen2.5:3b"
    assert router.model_name_for("unknown") == "qwen2.5:3b"
    assert router.get("intent") is router.get("intent")


def check_json_retry():
    fake_llm = FakeLLM(
        [
            "这不是 JSON",
            '{"value": "ok"}',
        ]
    )

    router = ModelRouter(
        routes={"query": "fake", "default": "fake"},
        client_factory=lambda **kwargs: fake_llm,
        max_retries=1,
    )

    parsed, raw_text = router.invoke_json(
        role="query",
        system_prompt="请只输出 JSON",
        human_prompt="测试",
        model_class=Answer,
    )

    assert parsed is not None
    assert parsed.value == "ok"
    assert raw_text == '{"value": "ok"}'

if __name__ == "__main__":
    main()
