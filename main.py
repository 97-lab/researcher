import json
from langchain_ollama import ChatOllama
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import ValidationError
from branch_store import BranchStore
from deep_researcher.configuration import INTENT_LLM
from deep_researcher.graph import DeepResearcher
from deep_researcher.prompts import (
    intent_parser_instructions,
    json_mode_intent_instructions,
)
from deep_researcher.schemas import UserIntent
from langchain_core.messages import SystemMessage, HumanMessage
from deep_researcher.memory import MemoryStore
from deep_researcher.tool_registry import ToolError
from deep_researcher.tool_specs import build_default_registry
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent


def parse_intent(llm, user_message: str) -> UserIntent:
    """把用户的一句话解析成结构化动作。"""
    messages = [
        SystemMessage(content=intent_parser_instructions + json_mode_intent_instructions),
        HumanMessage(content=user_message),
    ]
    response = llm.invoke(messages)
    try:
        data = json.loads(response.content)
        return UserIntent.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return UserIntent(action="unknown")


def print_branch(branch):
    """打印一个分支的搜索词和完整总结（含参考来源）。"""
    if not branch:
        print("找不到该分支。")
        return
    print(f"分支: {branch['researcher_id']} | 主题: {branch['topic']}")
    for i, q in enumerate(branch["queries"], 1):
        print(f"  第 {i} 轮搜索词: {q}")
    print("==== 总结（含参考来源）====")
    print(branch["summary"])

def print_memory_hits(hits):
    """打印 RAG 召回的历史版本。"""
    if not hits:
        print("没有找到相关的历史记忆。")
        return

    print(f"找到 {len(hits)} 条相关历史记忆：")
    for i, hit in enumerate(hits, 1):
        meta = hit["metadata"]
        print(
            f"--- 第 {i} 名 | 相关度: {hit['score']} "
            f"| 分支: {meta.get('researcher_id', '')}"
        )
        print(hit["content"])
        print()

def save_completed_branch(store, memory, researcher_id, thread_id, topic, result):
    """研究结束后同时更新两类存储：

    BranchStore：只保留当前版本（覆盖旧版本）
    MemoryStore：追加这个版本到 RAG 记忆（历史版本不会丢）
    """
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


def do_follow_up(graph, store, memory, branch, query_index, follow_up):
    """回到分支，对第 query_index 轮搜索词追问并重跑后续。"""
    config = {"configurable": {"thread_id": branch["thread_id"]}}
    snap = find_round_snapshot(graph, config, branch["queries"], query_index)
    if not snap:
        print(f"找不到第 {query_index} 轮搜索的时间点。")
        return
    # 第 1 步：把那一轮的搜索词替换成追问内容（改的是该时间点的状态）
    graph.update_state(
        snap.config,
        {
            "search_query": follow_up,
            "researcher_id": branch["researcher_id"],
        },
    )
    # 第 2 步：从修改后的时间点继续往后跑（web_research 会用新搜索词）
    result = graph.invoke(None, config=config)
    save_completed_branch(
        store,
        memory,
        branch["researcher_id"],
        branch["thread_id"],
        branch["topic"],
        result,
    )
    print("=== 追问后的新版本 ===")
    print_branch(store.get(branch["researcher_id"]))

def main():
    """程序入口：自然语言对话式研究。"""
    with SqliteSaver.from_conn_string(
            str(PROJECT_ROOT / "research.sqlite")
    ) as checkpointer:
        store = BranchStore(str(PROJECT_ROOT / "branches.sqlite"))
        memory = MemoryStore()
        # 工具在 main 里组装，图只依赖 ToolRegistry
        tool_registry = build_default_registry(memory)


        graph = DeepResearcher.build(
            checkpointer=checkpointer,
            tool_registry=tool_registry,
        )
        intent_llm = ChatOllama(model=INTENT_LLM, temperature=0, format="json")

        while True:
            msg = input("\n你想做什么？（""\n我可以\n 进行新的研究\n 查看过往研究\n 对过往研究追问\n  检索历史记忆\n 退出研究）").strip()
            if not msg:
                continue

            intent = parse_intent(intent_llm, msg)
            print("解析结果:", intent.model_dump())

            if intent.action == "exit":
                break

            elif intent.action == "new_research":
                if not intent.topic:
                    print("请告诉我研究什么主题。")
                    continue
                branch, created = store.get_or_create_by_topic(intent.topic)
                researcher_id = branch["researcher_id"]
                thread_id = branch["thread_id"]

                if created:
                    print(f"已创建新分支 {researcher_id}（主题：{intent.topic}）")
                else:
                    print(f"该主题已有分支 {researcher_id}，继续在该分支上研究")
                config = {"configurable": {"thread_id": thread_id}}
                result = graph.invoke(
                    {
                        "research_topic": intent.topic,
                        "researcher_id": researcher_id,
                    },
                    config=config,
                )

                save_completed_branch(
                    store,
                    memory,
                    researcher_id,
                    thread_id,
                    intent.topic,
                    result,
                )
                print(f"已创建分支记忆 {researcher_id}")
                print_branch(store.get(researcher_id))

            elif intent.action == "view":
                print_branch(store.get(intent.researcher_id))

            elif intent.action == "recall":
                try:
                    observation = tool_registry.call(
                        "recall_memory",
                        query=msg,
                        researcher_id=intent.researcher_id,
                        limit=1,
                    )
                except ToolError as exc:
                    print(f"记忆检索失败：{exc}")
                    continue
                print_memory_hits(observation["hits"])

            elif intent.action == "follow_up":
                branch = store.get(intent.researcher_id)
                if not branch:
                    print("找不到该分支。")
                    continue
                if intent.query_index < 1:
                    print("请说明追问第几个搜索词，例如：追问 r1 2 祖冲之的算法")
                    continue
                do_follow_up(graph, store, memory, branch, intent.query_index, intent.follow_up)


if __name__ == "__main__":
            main()
