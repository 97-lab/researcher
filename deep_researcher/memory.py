import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

from .configuration import OLLAMA_BASE_URL


DEFAULT_MIN_SCORE = 0.3

def distance_to_score(distance: float) -> float:
    """把 Chroma 的距离换算成余弦相似度。

    当前集合：space = l2，返回的是平方 L2 距离；
    qwen3-embedding 向量已归一化，因此：
    cosine = 1 - distance / 2
    """
    return 1.0 - distance / 2.0


def build_recall_filter(
    researcher_id: str = "",
    thread_id: str = "",
    kind: str = "",
):
    """把分支过滤条件转成 Chroma 的 where 结构。"""
    conditions = []

    if researcher_id:
        conditions.append({"researcher_id": researcher_id})

    if thread_id:
        conditions.append({"thread_id": thread_id})

    if kind:
        conditions.append({"kind": kind})

    if not conditions:
        return None

    if len(conditions) == 1:
        return conditions[0]

    return {"$and": conditions}


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
            return ""

        memory_id = f"{researcher_id}-{uuid.uuid4().hex[:12]}"
        document = self._build_document(version)

        metadata = {
            "researcher_id": researcher_id,
            "thread_id": version.get("thread_id", ""),
            "topic": version.get("topic", ""),
            "kind": version.get("kind", "research_version"),
            # queries 是列表，Chroma 的 metadata 只接受标量，所以先转 JSON 字符串
            "queries": json.dumps(version.get("queries", []), ensure_ascii=False),
            "remembered_at": datetime.now().isoformat(timespec="seconds"),
        }

        self.vectorstore.add_texts(
            texts=[document],
            metadatas=[metadata],
            ids=[memory_id],
        )

        return memory_id

    def recall(
        self,
        query,
        researcher_id="",
        thread_id="",
        kind="",
        limit=5,
        min_score=DEFAULT_MIN_SCORE,
    ):
        """用一句自然语言找回最相关的历史版本。

        只返回相关度 >= min_score 的记忆，避免把无关旧记忆一起打印。
        """
        if not query.strip():
            return []

        where = build_recall_filter(
            researcher_id=researcher_id,
            thread_id=thread_id,
            kind=kind,
        )

        try:
            # similarity_search_with_score 返回的是“距离”，越小越相似
            docs = self.vectorstore.similarity_search_with_score(
                query=query,
                k=limit,
                filter=where,
            )
        except Exception:
            return []

        results = []
        for doc, distance in docs:
            # 集合用的是余弦距离：距离 0 表示最相似
            # 转成相关度：1 - 距离 = 余弦相似度，越高越相关
            score = distance_to_score(distance)
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

