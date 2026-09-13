import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

from .configuration import OLLAMA_BASE_URL


DEFAULT_MIN_SCORE = 0.3
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "qwen3-embedding:0.6b")
DEFAULT_DB_DIR = str(Path(__file__).resolve().parents[1] / "memory_store")


class MemoryStore:

    def __init__(self, db_dir=DEFAULT_DB_DIR, collection_name="branch_version_memory"):
        self.embedding = OllamaEmbeddings(
            model=EMBEDDING_MODEL,
            base_url=OLLAMA_BASE_URL,
        )
        self.vectorstore = Chroma(
            collection_name=collection_name,
            persist_directory=db_dir,
            embedding_function=self.embedding,
        )

    def _build_document(self, version):
        """把一个版本拼成一段完整文字，向量检索搜的就是这段话。"""
        topic = version.get("topic", "")
        queries = version.get("queries", []) or []
        summary = version.get("summary", "")

        if queries:
            queries_text = "、".join(queries)
        else:
            queries_text = "（无搜索词）"

        return (
            f"研究主题：{topic}\n"
            f"搜索词：{queries_text}\n"
            f"总结：{summary}"
        )

    def remember(self, version):
        """把一个完整分支版本写进档案馆，返回记忆 id。"""
        researcher_id = version.get("researcher_id", "")
        summary = version.get("summary", "")

        if not researcher_id or not summary:
            print("[MemoryStore] 版本缺少 researcher_id 或 summary，已跳过。")
            return ""

        memory_id = f"{researcher_id}-{uuid.uuid4().hex[:12]}"
        document = self._build_document(version)

        metadata = {
            "researcher_id": researcher_id,
            "thread_id": version.get("thread_id", ""),
            "topic": version.get("topic", ""),
            # queries 是列表，Chroma 的 metadata 只接受标量，所以先转 JSON 字符串
            "queries": json.dumps(version.get("queries", []), ensure_ascii=False),
            "remembered_at": datetime.now().isoformat(timespec="seconds"),
        }

        self.vectorstore.add_texts(
            texts=[document],
            metadatas=[metadata],
            ids=[memory_id],
        )

        print(f"[MemoryStore] 已存档 {researcher_id} 的版本 -> {memory_id}")
        return memory_id

    def recall(self, query, researcher_id="", limit=5, min_score=DEFAULT_MIN_SCORE):
        """用一句自然语言找回最相关的历史版本。

        只返回相关度 >= min_score 的记忆，避免把无关旧记忆一起打印。
        """
        if not query.strip():
            return []

        where = None
        if researcher_id:
            where = {"researcher_id": researcher_id}

        try:
            # similarity_search_with_score 返回的是“距离”，越小越相似
            docs = self.vectorstore.similarity_search_with_score(
                query=query,
                k=limit,
                filter=where,
            )
        except Exception as exc:
            print(f"[MemoryStore] 检索失败：{exc}")
            return []

        results = []
        for doc, distance in docs:
            # 集合用的是余弦距离：距离 0 表示最相似
            # 转成相关度：1 - 距离 = 余弦相似度，越高越相关
            score = 1.0 - distance / 2.0

            if score < min_score:
                continue

            results.append(
                {
                    "score": round(score, 4),
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                }
            )
        return results

