from 复刻1.deep_researcher.memory import MemoryStore


def print_hits(results):
    """把召回结果逐条打印出来。"""
    if not results:
        print("没有召回任何记忆。")
        return

    for i, hit in enumerate(results, 1):
        print(f"--- 第 {i} 名 | 相关度: {hit['score']}")
        print(hit["content"])
        print()


def main():
    # db_dir=None 表示只在内存里跑，测试结束就消失，不会写进 memory_store 文件夹
    store = MemoryStore(db_dir=None)

    # 模拟 r4 的“旧版本”：下一轮被覆盖前的内容
    old_r4 = {
        "researcher_id": "r4",
        "thread_id": "thread-r4",
        "topic": "圆周率的计算方法",
        "queries": ["祖冲之 圆周率 算法", "圆周率 精度 割圆术"],
        "summary": (
            "祖冲之把圆周率精算到小数点后第七位，"
            "并提出约率22/7与密率355/113，领先世界数百年。"
        ),
    }

    # 模拟 r4 被覆盖后的“新版本”：同一个主题，但内容完全不同
    new_r4 = {
        "researcher_id": "r4",
        "thread_id": "thread-r4",
        "topic": "圆周率的计算方法",
        "queries": ["圆周率 现代 计算记录", "圆周率 计算机 算法"],
        "summary": (
            "现代主要用计算机和 Chudnovsky 级数计算圆周率，"
            "目前纪录已达数十万亿位。"
        ),
    }

    # 再放一个无关分支，用来确认不会干扰结果
    other_r2 = {
        "researcher_id": "r2",
        "thread_id": "thread-r2",
        "topic": "LangGraph 的状态持久化",
        "queries": ["LangGraph checkpoint", "SQLite 状态保存"],
        "summary": "LangGraph 可以用 SqliteSaver 把图的状态保存到 SQLite。",
    }

    store.remember(old_r4)
    store.remember(new_r4)
    store.remember(other_r2)

    # 用一句口语化的问题，去问“被覆盖的旧版本说过什么”
    query = "祖冲之当年把圆周率算到了小数点后几位？"

    print("===== 搜索全部历史 =====")
    hits = store.recall(query, limit=3)
    print_hits(hits)

    print("===== 只搜索 r4 的历史 =====")
    hits_r4 = store.recall(query, researcher_id="r4", limit=3)
    print_hits(hits_r4)

    # 检查：最相关的结果应该包含祖冲之，而不是现代计算机算法
    if hits:
        top = hits[0]
        if "祖冲之" in top["content"]:
            print("检查通过：最相关的历史版本是祖冲之的旧版总结。")
        else:
            print("检查失败：最相关结果不是旧版本，请把输出发给我。")
    else:
        print("检查失败：一条结果都没有召回，请把输出发给我。")


if __name__ == "__main__":
    main()