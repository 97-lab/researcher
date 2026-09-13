import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import BaseModel, Field

from deep_researcher.tool_registry import ToolError, ToolRegistry, ToolSpec
from deep_researcher.tool_specs import build_default_registry


class EchoParams(BaseModel):
    text: str = Field(min_length=1, description="要回显的文本")


def echo(text: str) -> dict:
    return {"echo": text}


class FakeMemory:
    """假的记忆库，只用来测试工具注册，不依赖 Ollama。"""

    def recall(
        self,
        query,
        researcher_id="",
        limit=5,
        min_score=0.3,
    ):
        return [
            {
                "score": 0.91,
                "content": f"研究主题：圆周率\n总结：假记忆命中 {query}",
                "metadata": {
                    "researcher_id": researcher_id or "r1",
                },
            }
        ]


def main():
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

    print("已注册工具：")
    for tool in registry.list_tools():
        print("-", tool["name"], "|", tool["permission"])

    print("\n正常调用：", registry.call("echo", text="你好"))

    try:
        registry.call("echo", text="")
    except ToolError as exc:
        print("\n参数校验拦截成功：", exc)

    try:
        registry.call("not_exists")
    except ToolError as exc:
        print("\n未知工具拦截成功：", exc)

    default_registry = build_default_registry(FakeMemory())

    print("\n默认工具清单：")
    for tool in default_registry.list_tools():
        print("-", tool["name"], "|", tool["permission"])

    recall = default_registry.call(
        "recall_memory",
        query="圆周率旧版本",
        researcher_id="r1",
    )
    print("\n记忆工具返回：", recall)


if __name__ == "__main__":
    main()