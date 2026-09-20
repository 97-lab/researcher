import json
import re
import sqlite3
import uuid


class BranchStore:
    """研究主题与分支编号的映射表。

    规则：
    同一个主题只对应一个 researcher_id；
    新主题才分配新的 researcher_id。
    """

    def __init__(self, db_path="branches.sqlite"):
        self.conn = sqlite3.connect(db_path)
        self._create_tables()
        self._migrate()
        self.conn.commit()

    def _create_tables(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS branches (
                researcher_id TEXT PRIMARY KEY,
                thread_id TEXT,
                topic TEXT,
                topic_key TEXT,
                queries TEXT,
                summary TEXT,
                updated_at TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            )
            """
        )

    def _migrate(self):
        """兼容旧数据库：补 topic_key 列，并初始化编号计数器。"""
        columns = [row[1] for row in self.conn.execute("PRAGMA table_info(branches)")]

        if "topic_key" not in columns:
            self.conn.execute("ALTER TABLE branches ADD COLUMN topic_key TEXT")

        rows = self.conn.execute(
            """
            SELECT researcher_id, topic
            FROM branches
            WHERE topic_key IS NULL OR topic_key = ''
            """
        ).fetchall()

        for researcher_id, topic in rows:
            self.conn.execute(
                "UPDATE branches SET topic_key = ? WHERE researcher_id = ?",
                (self.normalize_topic(topic or ""), researcher_id),
            )

        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_branches_topic_key
            ON branches(topic_key)
            """
        )

        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'next_branch_number'"
        ).fetchone()

        if row is None:
            numbers = []
            all_rows = self.conn.execute(
                "SELECT researcher_id FROM branches"
            ).fetchall()
            for (researcher_id,) in all_rows:
                if researcher_id.startswith("r") and researcher_id[1:].isdigit():
                    numbers.append(int(researcher_id[1:]))

            start = max(numbers, default=0) + 1
            self.conn.execute(
                """
                INSERT INTO meta (key, value)
                VALUES ('next_branch_number', ?)
                """,
                (start,),
            )

        self.conn.commit()

    @staticmethod
    def normalize_topic(topic: str) -> str:
        """把主题变成用于查重的 key。

        '圆周率'、' 圆周率 '、'圆周 率' 会视为同一个主题。
        """
        text = (topic or "").strip().lower()
        text = re.sub(r"\s+", "", text)
        return text

    def _row_to_branch(self, row):
        if not row:
            return None
        return {
            "researcher_id": row[0],
            "thread_id": row[1],
            "topic": row[2],
            "queries": json.loads(row[3]) if row[3] else [],
            "summary": row[4] or "",
        }

    def find_by_topic(self, topic):
        """按主题查找已有分支，找不到返回 None。"""
        topic_key = self.normalize_topic(topic)
        row = self.conn.execute(
            """
            SELECT researcher_id, thread_id, topic, queries, summary
            FROM branches
            WHERE topic_key = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (topic_key,),
        ).fetchone()
        return self._row_to_branch(row)

    def list_branches(self):
        """列出所有分支，最近的排前面。"""
        rows = self.conn.execute(
            """
            SELECT researcher_id, thread_id, topic, queries, summary
            FROM branches
            ORDER BY updated_at DESC
            """
        ).fetchall()

        branches = []
        for row in rows:
            branches.append(self._row_to_branch(row))
        return branches

    def find_branch_for_message(self, message):
        """在用户的话里找“已经研究过的主题”，取最长匹配。"""
        normalized_message = self.normalize_topic(message)
        best_branch = None
        best_length = 0

        for branch in self.list_branches():
            topic_key = self.normalize_topic(branch["topic"])
            if not topic_key:
                continue

            if (
                topic_key in normalized_message
                and len(topic_key) > best_length
            ):
                best_branch = branch
                best_length = len(topic_key)

        return best_branch

    def _next_number(self):
        """从持久化计数器分配下一个编号，不依赖当前行数。"""
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'next_branch_number'"
        ).fetchone()

        if row is None:
            number = 1
            self.conn.execute(
                """
                INSERT INTO meta (key, value)
                VALUES ('next_branch_number', ?)
                """,
                (number + 1,),
            )
        else:
            number = int(row[0])
            self.conn.execute(
                """
                UPDATE meta
                SET value = ?
                WHERE key = 'next_branch_number'
                """,
                (number + 1,),
            )

        self.conn.commit()
        return number

    def create_branch(self, topic):
        """创建一个新主题分支。"""
        topic_key = self.normalize_topic(topic)
        number = self._next_number()
        researcher_id = f"r{number}"
        thread_id = f"thread-{researcher_id}-{uuid.uuid4().hex[:6]}"

        self.conn.execute(
            """
            INSERT INTO branches
            (
                researcher_id,
                thread_id,
                topic,
                topic_key,
                queries,
                summary,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                researcher_id,
                thread_id,
                topic,
                topic_key,
                json.dumps([], ensure_ascii=False),
                "",
            ),
        )
        self.conn.commit()
        return self.get(researcher_id)

    def get_or_create_by_topic(self, topic):
        """按主题取分支：有就复用，没有就新建。

        返回 (branch, created)
        created=True 表示这次新建了分支。
        """
        existing = self.find_by_topic(topic)
        if existing is not None:
            return existing, False

        return self.create_branch(topic), True

    def next_id(self):
        """保留旧接口，但不建议继续使用。"""
        return f"r{self._next_number()}"

    def save(self, researcher_id, thread_id, topic, queries, summary):
        """保存或更新某个分支的当前版本。"""
        topic_key = self.normalize_topic(topic)
        self.conn.execute(
            """
            INSERT OR REPLACE INTO branches
            (
                researcher_id,
                thread_id,
                topic,
                topic_key,
                queries,
                summary,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                researcher_id,
                thread_id,
                topic,
                topic_key,
                json.dumps(queries, ensure_ascii=False),
                summary,
            ),
        )
        self.conn.commit()

    def get(self, researcher_id):
        """读取分支当前版本。"""
        row = self.conn.execute(
            """
            SELECT researcher_id, thread_id, topic, queries, summary
            FROM branches
            WHERE researcher_id = ?
            """,
            (researcher_id,),
        ).fetchone()
        return self._row_to_branch(row)
