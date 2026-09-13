from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
from pydantic import BaseModel, ValidationError
class ToolError(Exception):
    """工具调用失败时统一抛出的异常。"""
@dataclass
class ToolSpec:
    """一个工具的说明书。

    name        工具名，调用时使用
    description 工具说明，之后可以喂给模型
    parameters  参数模型，必须是 Pydantic BaseModel
    handler     真正干活的函数
    permission  权限标记：safe / network / write
    """

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
        """注册一个工具，名字不能重复。"""
        if spec.name in self._tools:
            raise ValueError(f"工具 {spec.name} 已经注册过了")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        """按名字取工具说明书。"""
        if name not in self._tools:
            raise ToolError(f"没有注册工具：{name}")
        return self._tools[name]

    def list_tools(self) -> list[dict]:
        """列出所有工具，返回可直接展示或喂给模型的结构。"""
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
        """统一调用入口。

        顺序：找工具 → 查权限 → 校验参数 → 执行 handler。
        """
        spec = self.get(name)

        if spec.permission not in self.allowed_permissions:
            raise ToolError(
                f"工具 {name} 的权限 {spec.permission} 未被允许，"
                f"当前允许：{sorted(self.allowed_permissions)}"
            )

        try:
            params = spec.parameters.model_validate(kwargs)
        except ValidationError as exc:
            raise ToolError(f"工具 {name} 参数校验失败：{exc}") from exc

        try:
            return spec.handler(**params.model_dump())
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"工具 {name} 执行失败：{exc}") from exc