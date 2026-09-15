import contextvars
import functools
import json
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

_current_recorder = contextvars.ContextVar(
    "current_trace_recorder",
    default=None,
)


def get_current_recorder():
    return _current_recorder.get()


@contextmanager
def use_recorder(recorder):
    """在 with 块内启用一个轨迹记录器。"""
    token = _current_recorder.set(recorder)
    try:
        yield recorder
    finally:
        _current_recorder.reset(token)


def summarize_value(value, max_chars=300):
    """把任意值变成适合写进 JSONL 的短摘要。"""
    if isinstance(value, dict):
        summary = {}
        for key, item in value.items():
            if isinstance(item, str):
                summary[key] = f"<str len={len(item)}>"
            elif isinstance(item, list):
                summary[key] = f"<list len={len(item)}>"
            elif isinstance(item, dict):
                summary[key] = f"<dict keys={list(item.keys())[:5]}>"
            else:
                summary[key] = str(item)[:max_chars]
        return summary

    if isinstance(value, str):
        return value[:max_chars]

    return str(value)[:max_chars]


def record_event(event, **data):
    """向当前轨迹记录器写一条事件；没有记录器时什么都不做。"""
    recorder = get_current_recorder()
    if recorder is None:
        return
    recorder.record(event, **data)


def trace_node(name):
    """节点装饰器：自动记录节点耗时、结果摘要和异常。"""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, state):
            start = time.perf_counter()
            try:
                result = func(self, state)
            except Exception as exc:
                record_event(
                    event="node_error",
                    node=name,
                    duration_ms=round(
                        (time.perf_counter() - start) * 1000,
                        2,
                    ),
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise

            record_event(
                event="node_end",
                node=name,
                duration_ms=round(
                    (time.perf_counter() - start) * 1000,
                    2,
                ),
                result=summarize_value(result),
            )
            return result

        return wrapper

    return decorator


class TraceRecorder:
    """一次运行的轨迹记录器，事件逐行写入 JSONL。"""

    def __init__(self, path, run_id):
        self.path = Path(path)
        self.run_id = run_id
        self.events = []
        self.started_at = time.perf_counter()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write({"event": "run_start"})

    @classmethod
    def create(cls, runs_dir="runs", label="run"):
        runs_dir = Path(runs_dir)
        safe_label = re.sub(
            r"[^0-9A-Za-z_\-]+",
            "_",
            label or "run",
        ).strip("_")
        if not safe_label:
            safe_label = "run"

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id = f"{safe_label}-{stamp}-{uuid.uuid4().hex[:6]}"
        return cls(runs_dir / f"{run_id}.jsonl", run_id)

    def _write(self, payload):
        event = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
        }
        event.update(payload)
        self.events.append(event)

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(event, ensure_ascii=False, default=str) + "\n"
            )

    def record(self, event, **data):
        payload = {"event": event}
        payload.update(data)
        self._write(payload)

    def finish(self, status="ok", **data):
        duration_ms = round(
            (time.perf_counter() - self.started_at) * 1000,
            2,
        )
        self.record("run_end", status=status, duration_ms=duration_ms, **data)

    def summary(self):
        nodes = 0
        tool_calls = 0
        errors = 0

        for event in self.events:
            if event["event"] == "node_end":
                nodes += 1
            elif event["event"] == "tool_call":
                tool_calls += 1
                if not event.get("ok", True):
                    errors += 1
            elif event["event"] == "node_error":
                errors += 1

        return {
            "nodes": nodes,
            "tool_calls": tool_calls,
            "errors": errors,
        }

    def summary_text(self):
        summary = self.summary()
        return (
            f"[trace] 文件: {self.path}\n"
            f"[trace] 节点: {summary['nodes']} | "
            f"工具调用: {summary['tool_calls']} | "
            f"错误: {summary['errors']}"
        )