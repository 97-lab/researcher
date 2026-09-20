from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from branch_store import BranchStore
from deep_researcher.conversation import (
    ConversationStore,
    answer_from_memory,
    resolve_clarification,
    understand_message,
)
from deep_researcher.graph import DeepResearcher
from deep_researcher.memory import MemoryStore
from deep_researcher.model_router import ModelRouter
from deep_researcher.prompts import (
    intent_parser_instructions,
    json_mode_intent_instructions,
)
from deep_researcher.schemas import UserIntent
from deep_researcher.tool_registry import ToolError
from deep_researcher.tool_specs import build_default_registry
from deep_researcher.trace import TraceRecorder, use_recorder
from deep_researcher.utils import deduplicate_sources


PROJECT_ROOT = Path(__file__).resolve().parent
INPUT_PROMPT = "\n用户："
AGENT_PREFIX = "Agent："


def print_agent(text):
    print(f"{AGENT_PREFIX}{text}", flush=True)


def parse_intent_fallback(model_router, user_message):
    """对话理解失败时的兜底解析。"""
    parsed, raw_text = model_router.invoke_json(
        role="intent",
        system_prompt=(
            intent_parser_instructions + json_mode_intent_instructions
        ),
        human_prompt=user_message,
        model_class=UserIntent,
    )
    if parsed is None:
        return UserIntent(action="unknown")
    return parsed


def resolve_branch(store, active_researcher_id, user_message, explicit_id=""):
    """按优先级找分支：显式编号 → 消息主题匹配 → 当前活跃分支。"""
    if explicit_id:
        branch = store.get(explicit_id)
        if branch:
            return branch

    branch = store.find_branch_for_message(user_message)
    if branch:
        return branch

    if active_researcher_id:
        return store.get(active_researcher_id)

    return None


def run_with_trace(label, action, payload, func):
    """执行一段逻辑并写入轨迹；终端不输出调试信息。"""
    recorder = TraceRecorder.create(
        PROJECT_ROOT / "runs",
        label=label,
    )
    recorder.record("run_input", action=action, **payload)

    try:
        with use_recorder(recorder):
            result = func()
    except Exception as exc:
        recorder.finish(
            status="error",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise

    recorder.finish(status="ok")
    return result


def save_completed_branch(store, memory, researcher_id, thread_id, topic, result):
    """研究结束后双写 BranchStore 和 MemoryStore。"""
    queries = result.get("searched_queries", [])
    summary = result["summary"]

    store.save(researcher_id, thread_id, topic, queries, summary)
    memory.remember(
        {
            "researcher_id": researcher_id,
            "thread_id": thread_id,
            "topic": topic,
            "queries": queries,
            "summary": summary,
            "kind": "research_version",
        }
    )


def find_round_snapshot(graph, config, queries, query_index):
    """找到第 query_index 轮搜索开始之前的时间点快照。"""
    if query_index < 1 or query_index > len(queries):
        return None

    target_query = queries[query_index - 1]

    for snap in graph.get_state_history(config):
        values = snap.values or {}
        loop = values.get("research_loop_count") or 0
        if (
            loop == query_index - 1
            and values.get("search_query") == target_query
        ):
            return snap

    return None


def run_new_research(graph, store, memory, topic, conversation):
    """运行一次新研究。"""
    branch, created = store.get_or_create_by_topic(topic)
    researcher_id = branch["researcher_id"]
    thread_id = branch["thread_id"]
    config = {"configurable": {"thread_id": thread_id}}

    result = run_with_trace(
        label=f"new-{researcher_id}",
        action="new_research",
        payload={
            "topic": topic,
            "researcher_id": researcher_id,
            "reused": not created,
        },
        func=lambda: graph.invoke(
            {
                "research_topic": topic,
                "researcher_id": researcher_id,
                "thread_id": thread_id,
            },
            config=config,
        ),
    )

    save_completed_branch(
        store,
        memory,
        researcher_id,
        thread_id,
        topic,
        result,
    )
    conversation.update_active(researcher_id, thread_id, topic)
    return branch, result


def run_continue_research(
    graph,
    store,
    memory,
    branch,
    follow_up,
    query_index=None,
):
    """在既有分支上继续研究。"""
    config = {"configurable": {"thread_id": branch["thread_id"]}}

    if query_index is None:
        query_index = len(branch["queries"])
    if query_index < 1:
        query_index = 1

    snap = find_round_snapshot(
        graph,
        config,
        branch["queries"],
        query_index,
    )
    if not snap:
        return None

    def job():
        graph.update_state(
            snap.config,
            {
                "search_query": follow_up,
                "researcher_id": branch["researcher_id"],
                "thread_id": branch["thread_id"],
            },
        )
        return graph.invoke(None, config=config)

    result = run_with_trace(
        label=f"continue-{branch['researcher_id']}",
        action="continue_research",
        payload={
            "researcher_id": branch["researcher_id"],
            "query_index": query_index,
            "follow_up": follow_up,
        },
        func=job,
    )

    save_completed_branch(
        store,
        memory,
        branch["researcher_id"],
        branch["thread_id"],
        branch["topic"],
        result,
    )
    return result


def print_thinking():
    print_agent("思考中...")


def print_final_result(result):
    summary = (result.get("summary") or "").strip()
    if not summary:
        sources = deduplicate_sources(result.get("sources_gathered", []))
        if sources:
            print_agent(f"参考来源：\n{sources}")
        return
    print_agent(summary)


def main():
    """程序入口：对话式研究。"""
    with SqliteSaver.from_conn_string(
        str(PROJECT_ROOT / "research.sqlite")
    ) as checkpointer:
        store = BranchStore(str(PROJECT_ROOT / "branches.sqlite"))
        memory = MemoryStore()
        conversation = ConversationStore(
            str(PROJECT_ROOT / "conversation.sqlite")
        )

        model_router = ModelRouter()
        tool_registry = build_default_registry(memory)

        graph = DeepResearcher.build(
            checkpointer=checkpointer,
            tool_registry=tool_registry,
            model_router=model_router,
        )

        print_agent("你好，我是研究助手。你可以直接告诉我研究主题，也可以继续追问。")

        while True:
            msg = input(INPUT_PROMPT).strip()
            if not msg:
                continue

            context = conversation.snapshot()
            pending = context.get("pending_clarification")

            if pending:
                intent, remaining = resolve_clarification(
                    model_router,
                    store,
                    pending,
                    msg,
                )

                if intent is None:
                    if remaining is None:
                        print_agent("已取消本次追问。")
                        conversation.clear_pending()
                    else:
                        conversation.set_pending(remaining)
                        print_agent(remaining["question"])
                        for index, option in enumerate(
                            remaining["options"],
                            1,
                        ):
                            print(f"{index}. {option}")
                    conversation.append_turn("用户", msg)
                    continue

                conversation.clear_pending()
            else:
                intent = understand_message(
                    model_router,
                    msg,
                    context,
                    store.list_branches(),
                )

                if intent is None:
                    intent = parse_intent_fallback(model_router, msg)

                if intent.needs_clarification:
                    question = (
                        intent.clarification_question
                        or "你指的是哪个主题？"
                    )
                    options = intent.clarification_options
                    if not options:
                        options = [
                            branch["topic"]
                            for branch in store.list_branches()[:5]
                        ]

                    print_agent(question)
                    for index, option in enumerate(options, 1):
                        print(f"{index}. {option}")

                    pending_data = {
                        "original_message": msg,
                        "original_intent": intent.model_dump(),
                        "question": question,
                        "options": options,
                        "attempts": 0,
                    }
                    conversation.set_pending(pending_data)
                    conversation.append_turn("用户", msg)
                    conversation.append_turn("Agent", question)
                    continue

            query_text = (
                intent.standalone_query.strip()
                or intent.follow_up.strip()
                or intent.topic.strip()
                or msg
            )

            branch = resolve_branch(
                store,
                context.get("active_researcher_id", ""),
                query_text,
                intent.researcher_id,
            )

            if intent.action == "exit":
                print_agent("再见。")
                break

            conversation.append_turn(
                "用户",
                msg,
                researcher_id=branch["researcher_id"] if branch else "",
                thread_id=branch["thread_id"] if branch else "",
                topic=branch["topic"] if branch else "",
            )

            if intent.action == "view":
                if not branch:
                    print_agent("我没有找到对应的研究主题。")
                    continue

                print_agent(branch["summary"])
                conversation.update_active(
                    branch["researcher_id"],
                    branch["thread_id"],
                    branch["topic"],
                )
                conversation.append_turn(
                    "Agent",
                    branch["summary"],
                    researcher_id=branch["researcher_id"],
                    thread_id=branch["thread_id"],
                    topic=branch["topic"],
                )
                continue

            if intent.action in {"recall", "answer_from_memory"}:
                if branch:
                    print_thinking()
                    answer, hits = answer_from_memory(
                        model_router,
                        memory,
                        branch,
                        query_text,
                    )
                    if answer:
                        print_agent(answer)
                        conversation.append_turn(
                            "Agent",
                            answer,
                            researcher_id=branch["researcher_id"],
                            thread_id=branch["thread_id"],
                            topic=branch["topic"],
                        )
                        conversation.update_active(
                            branch["researcher_id"],
                            branch["thread_id"],
                            branch["topic"],
                        )
                        continue

                    result = run_continue_research(
                        graph,
                        store,
                        memory,
                        branch,
                        query_text,
                    )
                    if result:
                        print_final_result(result)
                        conversation.append_turn(
                            "Agent",
                            result.get("summary", ""),
                            researcher_id=branch["researcher_id"],
                            thread_id=branch["thread_id"],
                            topic=branch["topic"],
                        )
                        conversation.update_active(
                            branch["researcher_id"],
                            branch["thread_id"],
                            branch["topic"],
                        )
                        continue

                print_agent("没有找到相关历史记忆。")
                continue

            if intent.action == "new_research":
                topic = intent.topic.strip() or query_text
                if not topic:
                    print_agent("请告诉我研究主题。")
                    continue

                print_thinking()
                branch, result = run_new_research(
                    graph,
                    store,
                    memory,
                    topic,
                    conversation,
                )
                print_final_result(result)
                conversation.append_turn(
                    "Agent",
                    result.get("summary", ""),
                    researcher_id=branch["researcher_id"],
                    thread_id=branch["thread_id"],
                    topic=branch["topic"],
                )
                continue

            if intent.action in {"continue_research", "follow_up"}:
                if not branch:
                    print_agent("我没有找到对应的研究主题，请告诉我具体主题。")
                    continue

                print_thinking()
                result = run_continue_research(
                    graph,
                    store,
                    memory,
                    branch,
                    intent.follow_up.strip() or query_text,
                    intent.query_index if intent.query_index >= 1 else None,
                )

                if result:
                    print_final_result(result)
                    conversation.append_turn(
                        "Agent",
                        result.get("summary", ""),
                        researcher_id=branch["researcher_id"],
                        thread_id=branch["thread_id"],
                        topic=branch["topic"],
                    )
                    conversation.update_active(
                        branch["researcher_id"],
                        branch["thread_id"],
                        branch["topic"],
                    )
                else:
                    print_agent("找不到要追问的历史时间点。")
                continue

            print_agent("我没理解你的意思，可以换一种说法。")


if __name__ == "__main__":
    main()
