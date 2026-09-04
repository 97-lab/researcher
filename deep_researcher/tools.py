from tavily import TavilyClient
from 复刻1.deep_researcher.configuration import SEARCH_API, TAVILY_API_KEY


class WebResearchTools:
    """封装网页研究相关的工具：搜索、相关性过滤、来源去重。"""

    def __init__(
            self,
            max_results: int = 10,
            keep: int = 3,
            ratio: float = 0.3,
            search_api: str = SEARCH_API ):
        self.max_results = max_results
        self.keep = keep
        self.ratio = ratio
        self.search_api = search_api


    def search(self, query: str) -> list:
        """按配置的搜索引擎搜索，返回统一格式的 [{title, url, body}, ...]。"""
        if self.search_api == "tavily":
            return self._tavily_search(query)
        return self._bing_search(query)

    def _tavily_search(self, query: str) -> list:
        """用 Tavily API 搜索，结果归一化成 {title, url, body}。"""
        if not TAVILY_API_KEY:
            raise ValueError("缺少 TAVILY_API_KEY，请在 .env 中配置")

        client = TavilyClient(api_key=TAVILY_API_KEY)
        response = client.search(
            query,
            max_results=self.max_results,
            include_raw_content=False,
        )

        results = []
        for item in response.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "body": item.get("content", ""),
            })
        return results

    def filter_relevant(self, results: list, topic: str) -> list:
        """按字符重合度过滤相关结果，并截取前 keep 条。"""
        new_result = []
        for result in results:
            if self._is_relevant(result, topic):
                new_result.append(result)
        return new_result[:self.keep]

    def _is_relevant(self, result: dict, topic: str) -> bool:
        """判断一条结果是否与主题相关（字符重合比例法）。"""
        text = (result["title"] + result["body"]).lower()
        topic_chars = set(topic.lower().replace(" ", ""))
        if not topic_chars:
            return False
        text_chars = set(text.replace(" ", ""))
        overlap = len(topic_chars & text_chars)
        threshold = max(3, int(len(topic_chars) * self.ratio))
        return overlap >= threshold

    def deduplicate(self, source_lines: list) -> str:
        """按行去重并拼成纯文本。"""
        seen = set()
        unique = []
        for line in source_lines:
            if line.strip() and line not in seen:
                seen.add(line)
                unique.append(line)
        return "\n".join(unique)





