import os
from dotenv import load_dotenv

load_dotenv()

MAX_LOOPS = int(os.getenv("MAX_WEB_RESEARCH_LOOPS", "3"))
LOCAL_LLM = os.getenv("LOCAL_LLM", "deepseek-r1:8b")
INTENT_LLM = os.getenv("INTENT_LLM", LOCAL_LLM)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "10"))
SEARCH_KEEP_RESULTS = int(os.getenv("SEARCH_KEEP_RESULTS", "3"))
RELEVANCE_RATIO = float(os.getenv("RELEVANCE_RATIO", "0.3"))
SEARCH_API = os.getenv("SEARCH_API", "tavily")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
