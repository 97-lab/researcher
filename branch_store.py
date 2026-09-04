import json
import sqlite3


class BranchStore:
    """researcher_id 与分支当前版本的对应关系表。"""
    def __init__(self,db_path="branches.sqlite"):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS branches (
            researcher_id TEXT PRIMARY KEY,
                thread_id TEXT,
                topic TEXT,
                queries TEXT,
                summary TEXT,
                updated_at TEXT
        )
        """
        )
        self.conn.commit()

    def next_id(self):
        """
        自动生成下一个分支编号
        """
        rows=self.conn.execute("SELECT researcher_id FROM branches").fetchall()
        nums=[]
        for (rid,) in rows:
            if rid.startswith("r") and rid[1:].isdigit():
                nums.append(int(rid[1:]))
        return f'r{max(nums,default=0)+1}'

    def save(self, researcher_id, thread_id, topic, queries, summary):
        """保存（或覆盖）分支的当前版本。"""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO branches
            (researcher_id, thread_id, topic, queries, summary, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                researcher_id,
                thread_id,
                topic,
                json.dumps(queries, ensure_ascii=False),
                summary,
            ),
        )
        self.conn.commit()

    def get(self, researcher_id):
        """读取分支当前版本。"""
        row = self.conn.execute(
            "SELECT researcher_id, thread_id, topic, queries, summary FROM branches WHERE researcher_id=?",
            (researcher_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "researcher_id": row[0],
            "thread_id": row[1],
            "topic": row[2],
            "queries": json.loads(row[3]),
            "summary": row[4],
        }





