import os

from dotenv import load_dotenv

load_dotenv()

# 研究循环
MAX_LOOPS = int(os.getenv("MAX_WEB_RESEARCH_LOOPS", "3"))

# Ollama 服务地址
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# 模型档位：fast 用快模型，quality 用质量模型
MODEL_PROFILE = os.getenv("MODEL_PROFILE", "fast")
FAST_LLM = os.getenv("FAST_LLM", "qwen2.5:3b")
QUALITY_LLM = os.getenv("QUALITY_LLM", "qwen2.5:7b")

# 模型调用失败或 JSON 解析失败时的重试次数
MODEL_MAX_RETRIES = int(os.getenv("MODEL_MAX_RETRIES", "2"))

# 每个角色的模型；角色级环境变量优先级最高
LOCAL_LLM = os.getenv("LOCAL_LLM", FAST_LLM)
INTENT_LLM = os.getenv("INTENT_LLM", FAST_LLM)
QUERY_LLM = os.getenv("QUERY_LLM", FAST_LLM)
PLANNER_LLM = os.getenv("PLANNER_LLM", FAST_LLM)
CONVERSATION_LLM = os.getenv("CONVERSATION_LLM", FAST_LLM)

REVIEWER_LLM=os.getenv("REVIEWER_LLM", FAST_LLM)
MAX_REVIEW_ROUNDS = int(os.getenv("MAX_REVIEW_ROUNDS", "1"))



if MODEL_PROFILE == "quality":
    SUMMARIZE_LLM = os.getenv("SUMMARIZE_LLM", QUALITY_LLM)
    REFLECT_LLM = os.getenv("REFLECT_LLM", QUALITY_LLM)
else:
    SUMMARIZE_LLM = os.getenv("SUMMARIZE_LLM", FAST_LLM)
    REFLECT_LLM = os.getenv("REFLECT_LLM", FAST_LLM)

MODEL_ROUTES = {
    "conversation": CONVERSATION_LLM,
    "intent": INTENT_LLM,
    "planner": PLANNER_LLM,
    "reviewer": REVIEWER_LLM,
    "query": QUERY_LLM,
    "summarize": SUMMARIZE_LLM,
    "reflect": REFLECT_LLM,
    "default": FAST_LLM,
}
# 搜索与相关性
SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "10"))
SEARCH_KEEP_RESULTS = int(os.getenv("SEARCH_KEEP_RESULTS", "3"))
RELEVANCE_RATIO = float(os.getenv("RELEVANCE_RATIO", "0.3"))
SEARCH_API = os.getenv("SEARCH_API", "tavily")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# 上下文预算
CONTEXT_KEEP_LAST_OBSERVATIONS = int(
    os.getenv("CONTEXT_KEEP_LAST_OBSERVATIONS", "2")
)
CONTEXT_MAX_OBSERVATION_CHARS = int(
    os.getenv("CONTEXT_MAX_OBSERVATION_CHARS", "4000")
)
CONTEXT_MAX_MEMORY_CHARS = int(
    os.getenv("CONTEXT_MAX_MEMORY_CHARS", "2000")
)
