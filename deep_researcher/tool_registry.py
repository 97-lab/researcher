from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from .trace import record_event, summarize_value


class ToolError(Exception):
    """工具调用失败时统一抛出的异常。"""


@dataclass
class ToolSpec:
    """一个工具的说明书。"""

    name: str
    description: str
    parameters: type[BaseModel]
    handler: Callable[..., Any]
    permission: str = "safe"


class ToolRegistry:
    """工具注册表：负责登记、描述、校验和调用工具。"""

    def __init__(self, allowed_permissions=None):
        self._tools: dict[str, ToolSpec] = {}

        if allowed_permissions is None:
            allowed_permissions = {"safe", "network"}

        self.allowed_permissions = set(allowed_permissions)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"工具 {spec.name} 已经注册过了")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise ToolError(f"没有注册工具：{name}")
        return self._tools[name]

    def list_tools(self) -> list[dict]:
        tools = []
        for spec in self._tools.values():
            tools.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "permission": spec.permission,
                    "parameters": spec.parameters.model_json_schema(),
                }
            )
        return tools

    def call(self, name: str, **kwargs) -> Any:
        """统一调用入口：找工具 → 查权限 → 校验参数 → 执行 → 记录轨迹。"""
        start = time.perf_counter()

        try:
            spec = self.get(name)

            if spec.permission not in self.allowed_permissions:
                raise ToolError(
                    f"工具 {name} 的权限 {spec.permission} 未被允许，"
                    f"当前允许：{sorted(self.allowed_permissions)}"
                )

            try:
                params = spec.parameters.model_validate(kwargs)
            except ValidationError as exc:
                raise ToolError(
                    f"工具 {name} 参数校验失败：{exc}"
                ) from exc

            result = spec.handler(**params.model_dump())

        except ToolError as exc:
            record_event(
                event="tool_call",
                tool=name,
                ok=False,
                duration_ms=round(
                    (time.perf_counter() - start) * 1000,
                    2,
                ),
                args=summarize_value(kwargs),
                error=str(exc),
            )
            raise

        record_event(
            event="tool_call",
            tool=name,
            permission=spec.permission,
            ok=True,
            duration_ms=round(
                (time.perf_counter() - start) * 1000,
                2,
            ),
            args=summarize_value(kwargs),
            result=summarize_value(result),
        )
        return result
