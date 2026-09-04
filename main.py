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


def parse_intent(llm, user_message: str) -> UserIntent:
    """把用户的一句话解析成结构化动作。"""
    system_prompt = (
        intent_parser_instructions.format(user_message=user_message)
        + json_mode_intent_instructions
    )
    response = llm.invoke(system_prompt)
    try:
        data = json.loads(response.content)
        return UserIntent.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return UserIntent(action="unknown")



def print_branch(branch):
    """打印一个分支的搜索词和总结。"""
    if not branch:
        print("找不到该分支。")
        return
    print(f"分支: {branch['researcher_id']} | 主题: {branch['topic']}")
    for i, q in enumerate(branch["queries"], 1):
        print(f"  第 {i} 轮搜索词: {q}")
    print("总结:", branch["summary"][:200] + "...")



def find_round_checkpoint(graph, config, queries, query_index):
    """找到第 query_index 轮搜索开始之前的时间点。"""
    if query_index < 1 or query_index > len(queries):
        return None
    target_query = queries[query_index - 1]
    for snap in graph.get_state_history(config):
        values = snap.values or {}
        if (
            values.get("research_loop_count") == query_index - 1
            and values.get("search_query") == target_query
        ):
            return snap.config["configurable"]["checkpoint_id"]
    return None


def do_follow_up(graph, store, branch, query_index, follow_up):
    """回到分支，对第 query_index 轮搜索词追问并重跑后续。"""
    config = {"configurable": {"thread_id": branch["thread_id"]}}
    checkpoint_id = find_round_checkpoint(graph, config, branch["queries"], query_index)
    if not checkpoint_id:
        print(f"找不到第 {query_index} 轮搜索的时间点。")
        return

    time_config = {
        "configurable": {
            "thread_id": branch["thread_id"],
            "checkpoint_id": checkpoint_id,
        }
    }
    result = graph.invoke(
        {"research_topic": branch["topic"], "search_query": follow_up},
        config=time_config,
    )
    store.save(
        branch["researcher_id"],
        branch["thread_id"],
        branch["topic"],
        result.get("search_query_history") or branch["queries"],
        result["summary"],
    )
    print("=== 追问后的新版本 ===")
    print_branch(store.get(branch["researcher_id"]))


def main():
    """程序入口：自然语言对话式研究。"""
    with SqliteSaver.from_conn_string("research.sqlite") as checkpointer:
        graph = DeepResearcher.build(checkpointer=checkpointer)
        store = BranchStore("branches.sqlite")
        intent_llm = ChatOllama(model=INTENT_LLM, temperature=0, format="json")

        while True:
            msg = input("\n你想做什么？（研究/查看/追问/退出）：").strip()
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
                researcher_id = store.next_id()
                thread_id = f"thread-{researcher_id}"
                config = {"configurable": {"thread_id": thread_id}}
                result = graph.invoke({"research_topic": intent.topic}, config=config)
                store.save(
                    researcher_id,
                    thread_id,
                    intent.topic,
                    result.get("search_query_history", []),
                    result["summary"],
                )
                print(f"已创建分支记忆 {researcher_id}")
                print_branch(store.get(researcher_id))

            elif intent.action == "view":
                print_branch(store.get(intent.researcher_id))

            elif intent.action == "follow_up":
                branch = store.get(intent.researcher_id)
                if not branch:
                    print("找不到该分支。")
                    continue
                do_follow_up(graph, store, branch, intent.query_index, intent.follow_up)

            else:
                print("没听懂，换种说法试试。")




if __name__ == "__main__":
        main()
