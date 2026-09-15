import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import ValidationError

from .configuration import (
    MODEL_MAX_RETRIES,
    MODEL_ROUTES,
    OLLAMA_BASE_URL,
)


class ModelRouter:
    """按角色选择模型，并缓存已经创建好的客户端。"""

    def __init__(
        self,
        routes=None,
        base_url=OLLAMA_BASE_URL,
        max_retries=MODEL_MAX_RETRIES,
        client_factory=None,
    ):
        self.routes = dict(routes or MODEL_ROUTES)
        self.base_url = base_url
        self.max_retries = max_retries
        self.client_factory = client_factory or ChatOllama
        self._cache = {}

    def model_name_for(self, role: str) -> str:
        """返回某个角色应该使用的模型名。"""
        return (
            self.routes.get(role)
            or self.routes.get("default")
            or "qwen2.5:3b"
        )

    def get(self, role: str, json_mode=False, temperature=0):
        """获取某个角色的聊天模型；相同参数会复用同一个客户端。"""
        key = (role, json_mode, temperature)

        if key not in self._cache:
            kwargs = {
                "model": self.model_name_for(role),
                "base_url": self.base_url,
                "temperature": temperature,
            }
            if json_mode:
                kwargs["format"] = "json"
            self._cache[key] = self.client_factory(**kwargs)

        return self._cache[key]

    def invoke_json(
        self,
        role: str,
        system_prompt: str,
        human_prompt: str,
        model_class,
    ):
        """调用 JSON 模型并校验。

        成功：返回 (Pydantic 对象, 原始文本)
        失败：返回 (None, 最后一次原始文本)
        """
        llm = self.get(role, json_mode=True)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ]

        last_text = ""

        for attempt in range(self.max_retries + 1):
            try:
                response = llm.invoke(messages)
                last_text = response.content or ""
            except Exception as exc:
                last_text = f"{type(exc).__name__}: {exc}"
                if attempt >= self.max_retries:
                    return None, last_text
                continue

            try:
                data = json.loads(last_text)
                parsed = model_class.model_validate(data)
                return parsed, last_text
            except (json.JSONDecodeError, ValidationError):
                if attempt >= self.max_retries:
                    return None, last_text

                messages.append(
                    SystemMessage(
                        content=(
                            "你上一次的输出不是合法 JSON，无法解析。"
                            "请只输出一个 JSON 对象，"
                            "不要 Markdown 代码块，不要解释。"
                        )
                    )
                )
                messages.append(
                    HumanMessage(content="请重新输出符合要求的纯 JSON。")
                )

        return None, last_text