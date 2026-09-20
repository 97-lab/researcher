import json
import sqlite3
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage

from .prompts import (
    clarification_resolver_instructions,
    conversation_understanding_instructions,
    memory_answer_instructions,
)
from .schemas import ClarificationChoice, UserIntent


class ConversationStore:
    """保存最近对话和当前会话状态。"""

    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                researcher_id TEXT DEFAULT '',
                thread_id TEXT DEFAULT '',
                topic TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        self.conn.commit()

    def append_turn(
        self,
        role,
        content,
        researcher_id="",
        thread_id="",
        topic="",
    ):
        self.conn.execute(
            """
            INSERT INTO turns
            (role, content, researcher_id, thread_id, topic, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                role,
                content,
                researcher_id,
                thread_id,
                topic,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()

    def recent_turns(self, limit=5):
        rows = self.conn.execute(
            """
            SELECT role, content, researcher_id, thread_id, topic
            FROM turns
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        turns = []
        for row in reversed(rows):
            turns.append(
                {
                    "role": row[0],
                    "content": row[1],
                    "researcher_id": row[2],
                    "thread_id": row[3],
                    "topic": row[4],
                }
            )
        return turns

    def get_state(self, key, default=None):
        row = self.conn.execute(
            "SELECT value FROM state WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return default

        try:
            return json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return row[0]

    def set_state(self, key, value):
        self.conn.execute(
            """
            INSERT OR REPLACE INTO state (key, value)
            VALUES (?, ?)
            """,
            (key, json.dumps(value, ensure_ascii=False)),
        )
        self.conn.commit()

    def snapshot(self):
        return {
            "active_topic": self.get_state("active_topic", ""),
            "active_researcher_id": self.get_state(
                "active_researcher_id",
                "",
            ),
            "active_thread_id": self.get_state("active_thread_id", ""),
            "pending_clarification": self.get_state(
                "pending_clarification",
                None,
            ),
            "recent_turns": self.recent_turns(5),
        }

    def update_active(self, researcher_id, thread_id, topic):
        self.set_state("active_researcher_id", researcher_id)
        self.set_state("active_thread_id", thread_id)
        self.set_state("active_topic", topic)

    def set_pending(self, pending):
        self.set_state("pending_clarification", pending)

    def clear_pending(self):
        self.set_state("pending_clarification", None)


def format_branches(branches):
    lines = []
    for branch in branches:
        lines.append(f"{branch['researcher_id']}: {branch['topic']}")
    if not lines:
        return "（暂无已有分支）"
    return "\n".join(lines)


def format_turns(turns, max_chars=300):
    lines = []
    for turn in turns:
        content = turn["content"]
        if len(content) > max_chars:
            content = content[:max_chars] + "..."
        lines.append(f"{turn['role']}：{content}")
    if not lines:
        return "（暂无最近对话）"
    return "\n".join(lines)


def understand_message(model_router, user_message, context, branches):
    """结合会话上下文理解用户最新一句话。"""
    active_topic = context.get("active_topic") or "（无）"
    branch_text = format_branches(branches)
    turn_text = format_turns(context.get("recent_turns", []))

    human_prompt = (
        f"当前活跃主题：{active_topic}\n\n"
        f"已有分支：\n{branch_text}\n\n"
        f"最近对话：\n{turn_text}\n\n"
        f"用户最新消息：{user_message}\n\n"
        f"请输出对话理解结果。"
    )

    parsed, raw_text = model_router.invoke_json(
        role="conversation",
        system_prompt=conversation_understanding_instructions,
        human_prompt=human_prompt,
        model_class=UserIntent,
    )
    return parsed


def resolve_clarification(
    model_router,
    branch_store,
    pending,
    user_answer,
):
    """解析用户对反问的回答，返回 (UserIntent, pending)。"""
    answer = (user_answer or "").strip()

    if answer in {"取消", "算了", "不查了"}:
        return None, None

    branch = branch_store.get(answer)
    if branch is None:
        branch = branch_store.find_branch_for_message(answer)

    if branch is None:
        number_map = {
            "第一个": 1,
            "第1个": 1,
            "1": 1,
            "第二个": 2,
            "第2个": 2,
            "2": 2,
            "第三个": 3,
            "第3个": 3,
            "3": 3,
        }
        index = number_map.get(answer)
        options = pending.get("options", [])
        if index is not None and 1 <= index <= len(options):
            branch = branch_store.find_branch_for_message(
                options[index - 1]
            )

    standalone_query = answer

    if branch is None:
        candidate_text = format_branches(branch_store.list_branches())
        human_prompt = (
            f"原始问题：{pending.get('original_message', '')}\n"
            f"反问：{pending.get('question', '')}\n"
            f"候选主题：\n{candidate_text}\n"
            f"用户回答：{answer}\n"
        )
        parsed, raw_text = model_router.invoke_json(
            role="conversation",
            system_prompt=clarification_resolver_instructions,
            human_prompt=human_prompt,
            model_class=ClarificationChoice,
        )

        if parsed is None or not parsed.resolved:
            pending["attempts"] = pending.get("attempts", 0) + 1
            return None, pending

        branch = branch_store.get(parsed.researcher_id)
        if branch is None:
            pending["attempts"] = pending.get("attempts", 0) + 1
            return None, pending

        standalone_query = parsed.standalone_query or answer

    original = pending.get("original_intent", {})
    intent = UserIntent.model_validate(original)
    intent.researcher_id = branch["researcher_id"]
    intent.topic = branch["topic"]
    intent.standalone_query = standalone_query
    intent.follow_up = standalone_query
    intent.needs_clarification = False
    intent.clarification_question = ""
    intent.clarification_options = []

    if intent.action in {"new_research", "unknown"}:
        intent.action = "continue_research"

    return intent, None


def answer_from_memory(model_router, memory, branch, query):
    """尝试只用历史记忆回答问题。"""
    hits = memory.recall(
        query=query,
        researcher_id=branch["researcher_id"],
        thread_id=branch["thread_id"],
        limit=3,
    )

    if not hits:
        return None, []

    memory_text = "\n\n".join(hit["content"] for hit in hits)

    llm = model_router.get("conversation")
    messages = [
        SystemMessage(content=memory_answer_instructions),
        HumanMessage(
            content=(
                f"用户问题：{query}\n\n"
                f"历史记忆：\n{memory_text}\n\n"
                f"请只用历史记忆回答。"
            )
        ),
    ]
    response = llm.invoke(messages)
    answer = (response.content or "").strip()

    if not answer or "现有记忆不足" in answer:
        return None, hits

    return answer, hits
