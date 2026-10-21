import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from .configuration import (
    CLOUD_API_BASE,
    CLOUD_API_KEY,
    CLOUD_MODELS,
    CLOUD_ROLES,
    MODEL_MAX_RETRIES,
    MODEL_ROUTES,
    OLLAMA_BASE_URL,
)


class ModelRouter:
    """按角色选择模型，并缓存已经创建好的客户端。

    配了 CLOUD_API_KEY 且角色在 CLOUD_ROLES 里就走云端（OpenAI 兼容 API），
    否则走本地 Ollama。不配云端时行为与以前完全一致。
    """

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
        self._cloud_roles = {
            item.strip() for item in CLOUD_ROLES.split(",") if item.strip()
        }
        self._cloud_models = {}
        for item in CLOUD_MODELS.split(","):
            if "=" in item:
                role, model = item.split("=", 1)
                self._cloud_models[role.strip()] = model.strip()
        self._cache = {}

    def _use_cloud(self, role: str) -> bool:
        """判断某个角色是否走云端：必须配了 key，且角色在云端清单里。"""
        if not (CLOUD_API_KEY and CLOUD_API_BASE):
            return False
        return "all" in self._cloud_roles or role in self._cloud_roles

    def model_name_for(self, role: str) -> str:
        """返回某个角色应该使用的模型名。"""
        if self._use_cloud(role):
            return (
                self._cloud_models.get(role)
                or self._cloud_models.get("default")
                or self._local_model_name(role)
            )
        return self._local_model_name(role)

    def _local_model_name(self, role: str) -> str:
        """本地 Ollama 用的模型名。"""
        return (
            self.routes.get(role)
            or self.routes.get("default")
            or "qwen2.5:3b"
        )

    def get(self, role: str, json_mode=False, temperature=0):
        """获取某个角色的聊天模型；相同参数会复用同一个客户端。"""
        key = (role, json_mode, temperature)

        if key not in self._cache:
            model = self.model_name_for(role)

            if self._use_cloud(role):
                kwargs = {
                    "model": model,
                    "base_url": CLOUD_API_BASE,
                    "api_key": CLOUD_API_KEY,
                    "temperature": temperature,
                }
                if json_mode:
                    kwargs["model_kwargs"] = {
                        "response_format": {"type": "json_object"}
                    }
                self._cache[key] = ChatOpenAI(**kwargs)
            else:
                kwargs = {
                    "model": model,
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