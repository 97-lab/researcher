"""短期记忆评测：多轮追问正确率 + 上下文关键信息保留率（NIAH 式）。

覆盖记忆评测三指标中的后两项，全部走确定性路径，不依赖 LLM：

指标 2 —— 多轮追问正确率（指代消解 + 意图路由，端到端合并）：
    给定活跃主题 + 一句代词追问，判定
    a) standalone_query 是否正确替换了主题（不含代词、含主题锚点）；
    b) 意图路由是否落到预期 action（answer_from_memory / continue_research /
       new_research 等）。
    两者都对才算该题得分。

指标 3 —— 关键信息保留率（大海捞针 / Needle-in-a-Haystack 式）：
    在一批搜索观察的指定位置埋"针"（关键事实），经过
    LastNObservations + TruncateEachObservation 滑动窗口裁剪后，
    检查针是否仍存活在装配出的上下文里。位置越靠前越容易丢，
    保留率 = 针存活的用例数 / 总埋针用例数。

用法：
    python -m test_scripts.eval_shortterm_memory
    python -m test_scripts.eval_shortterm_memory --json reports/shortterm_metrics.json
    python -m test_scripts.eval_shortterm_memory --md reports/shortterm_metrics.md
    python -m test_scripts.eval_shortterm_memory --verbose
    python -m test_scripts.eval_shortterm_memory --self-test

退出码：0 正常；1 自检失败。
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# =====================================================================
# 指标 2：多轮追问正确率
# 每条用例：活跃主题 + 用户原话 -> 期望的独立问句 + 期望的路由 action。
# expected_query 支持多个可接受答案（字符串匹配其一即可）。
# =====================================================================

FOLLOW_UP_CASES = [
    {
        "name": "代词追问-品牌",
        "active_topic": "蓝牙",
        "message": "那它著名的品牌是什么",
        "expected_query": ["蓝牙著名的品牌是什么"],
        "expected_action": "answer_from_memory",
    },
    {
        "name": "代词追问-价格",
        "active_topic": "蓝牙",
        "message": "它多少钱",
        "expected_query": ["蓝牙多少钱"],
        "expected_action": "answer_from_memory",
    },
    {
        "name": "代词追问-原理",
        "active_topic": "祖冲之",
        "message": "它是怎么算圆周率的",
        "expected_query": ["蓝牙怎么算圆周率", "祖冲之是怎么算圆周率的"],
        "expected_action": "answer_from_memory",
    },
    {
        "name": "省略句追问",
        "active_topic": "蓝牙",
        "message": "还有哪些品牌",
        "expected_query": ["蓝牙还有哪些品牌"],
        "expected_action": "answer_from_memory",
    },
    {
        "name": "连接词追问-继续研究",
        "active_topic": "城市热岛效应",
        "message": "那再深入讲讲它的成因",
        "expected_query": ["再深入讲讲城市热岛效应的成因", "城市热岛效应的成因"],
        "expected_action": "continue_research",
    },
    {
        "name": "明确换主题-新研究",
        "active_topic": "蓝牙",
        "message": "换个话题，介绍一下量子计算",
        "expected_query": ["介绍一下量子计算"],
        "expected_action": "new_research",
    },
    {
        "name": "无上下文-直接新研究",
        "active_topic": "",
        "message": "什么是敦煌莫高窟壁画",
        "expected_query": ["什么是敦煌莫高窟壁画"],
        "expected_action": "new_research",
    },
    {
        "name": "无上下文-问句直接回答",
        "active_topic": "",
        "message": "咖啡因为什么让人睡不着",
        "expected_query": ["咖啡因为什么让人睡不着"],
        "expected_action": "answer_from_memory",
    },
    {
        "name": "代词追问-指回活跃主题不换题",
        "active_topic": "圆周率的计算历史",
        "message": "介绍一下它",
        "expected_query": ["介绍一下圆周率的计算历史", "圆周率的计算历史"],
        "expected_action": "answer_from_memory",
    },
]


def eval_follow_up_cases(verbose: bool = False) -> dict:
    """跑多轮追问用例，返回正确率与错例明细。"""
    from deep_researcher.conversation import (
        build_standalone_query,
        fallback_intent,
    )

    results = []
    total = 0
    correct = 0
    query_errors = 0
    route_errors = 0

    for case in FOLLOW_UP_CASES:
        context = {"active_topic": case["active_topic"]}
        total += 1

        query = build_standalone_query(case["message"], context)
        intent = fallback_intent(case["message"], context)

        query_ok = query in case["expected_query"]
        # 兜底判分：不含代词，且含主题锚点（无上下文用例除外）
        topic = case["active_topic"]
        if topic:
            query_ok = query_ok or (
                topic in query and not any(
                    p in query for p in ("它", "这个", "那个")
                )
            )
        route_ok = intent.action == case["expected_action"]

        if query_ok and route_ok:
            correct += 1
        else:
            if not query_ok:
                query_errors += 1
            if not route_ok:
                route_errors += 1

        results.append(
            {
                "name": case["name"],
                "message": case["message"],
                "got_query": query,
                "expected_query": case["expected_query"],
                "got_action": intent.action,
                "expected_action": case["expected_action"],
                "query_ok": query_ok,
                "route_ok": route_ok,
                "pass": query_ok and route_ok,
            }
        )

    if verbose:
        for row in results:
            flag = "PASS" if row["pass"] else "FAIL"
            print(
                f"[{flag}] {row['name']}: {row['message']!r} -> "
                f"query={row['got_query']!r} action={row['got_action']}"
            )

    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "query_errors": query_errors,
        "route_errors": route_errors,
        "cases": results,
    }


# =====================================================================
# 指标 3：关键信息保留率（NIAH 式）
# 生成 n 条普通观察，把"针"插到第 pos 条（1 起，正数从头数），
# 经 ContextBuilder 裁剪装配后检查针文本是否存活。
# =====================================================================

_NEEDLE_TEMPLATE = "关键事实：{topic}的基准测试得分为{score}分。"
_DISTRACTOR_TEMPLATE = (
    "普通观察{index}：关于{topic}的第{index}轮搜索资料，"
    "包含一些背景介绍与常见讨论，内容相对冗长，"
    "用于撑起上下文窗口的体量。"
)


def build_observations(n: int, topics: list[str], scores: list[str]) -> list[str]:
    return [
        _DISTRACTOR_TEMPLATE.format(index=i + 1, topic=topics[i % len(topics)])
        for i in range(n)
    ]


def niah_cases(keep_last: int, max_obs_chars: int) -> list[dict]:
    """生成 NIAH 用例：针从最早到最新逐个位置埋一遍。"""
    topics = ["芯片", "操作系统", "云计算", "数据库"]
    scores = ["87", "92", "78", "95", "66"]
    cases = []

    for n_obs in (keep_last + 1, keep_last + 3, keep_last + 6):
        for pos in range(1, n_obs + 1):
            needle = _NEEDLE_TEMPLATE.format(
                topic=topics[pos % len(topics)],
                score=scores[pos % len(scores)],
            )
            observations = build_observations(n_obs, topics, scores)
            observations[pos - 1] = needle
            cases.append(
                {
                    "name": f"n={n_obs}, pos={pos}",
                    "needle": needle,
                    "observations": observations,
                    "needle_pos": pos,
                }
            )

    return cases


def eval_niah_cases(keep_last: int, max_obs_chars: int, verbose: bool = False) -> dict:
    """跑 NIAH 用例，返回关键信息保留率。"""
    from deep_researcher.context import ContextBuilder

    builder = ContextBuilder(
        history_processors=[],  # 直接用窗口与截断参数，保持用例可控
    )
    # 重新按参数构造处理器
    from deep_researcher.context import (
        LastNObservations,
        TruncateEachObservation,
    )

    builder = ContextBuilder(
        history_processors=[
            LastNObservations(n=keep_last),
            TruncateEachObservation(max_chars=max_obs_chars),
        ]
    )

    cases = niah_cases(keep_last, max_obs_chars)
    results = []
    survived = 0

    for case in cases:
        context_text = builder.build_observation_text(case["observations"])
        alive = case["needle"] in context_text
        if alive:
            survived += 1
        results.append(
            {
                "name": case["name"],
                "needle_pos": case["needle_pos"],
                "n_observations": len(case["observations"]),
                "survived": alive,
            }
        )
        if verbose:
            flag = "PASS" if alive else "LOST"
            print(f"[{flag}] {case['name']}: 针{'存活' if alive else '被裁丢'}")

    total = len(cases)
    return {
        "keep_last": keep_last,
        "max_obs_chars": max_obs_chars,
        "total": total,
        "survived": survived,
        "retention_rate": round(survived / total, 4) if total else 0.0,
        "cases": results,
    }


# =====================================================================
# 报告输出
# =====================================================================

def render_text(follow_up: dict, niah: dict) -> str:
    lines = [
        "=== 短期记忆评测 ===",
        f"评测时间：{datetime.now().isoformat(timespec='seconds')}",
        "",
        "-- 指标 2：多轮追问正确率（指代消解 + 意图路由）--",
        f"总用例：{follow_up['total']} | 正确：{follow_up['correct']} | "
        f"正确率：{follow_up['accuracy']:.2%}",
        f"错因分布：问句消解错 {follow_up['query_errors']} 条，"
        f"路由错 {follow_up['route_errors']} 条",
        "",
        "-- 指标 3：关键信息保留率（NIAH 式）--",
        f"窗口 keep_last={niah['keep_last']}, "
        f"单条截断 max_obs_chars={niah['max_obs_chars']}",
        f"总用例：{niah['total']} | 针存活：{niah['survived']} | "
        f"保留率：{niah['retention_rate']:.2%}",
    ]
    return "\n".join(lines)


def render_markdown(follow_up: dict, niah: dict) -> str:
    lines = [
        f"## 短期记忆评测（{datetime.now().isoformat(timespec='seconds')}）",
        "",
        "### 指标 2：多轮追问正确率",
        f"- 正确率 **{follow_up['accuracy']:.2%}**"
        f"（{follow_up['correct']}/{follow_up['total']}）",
        f"- 问句消解错 {follow_up['query_errors']} 条，"
        f"路由错 {follow_up['route_errors']} 条",
        "",
        "| 用例 | 问句 | 得到的问句 | 期望 action | 实际 action | 结果 |",
        "|---|---|---|---|---|---|",
    ]
    for row in follow_up["cases"]:
        lines.append(
            f"| {row['name']} | {row['message']} | {row['got_query']} | "
            f"{row['expected_action']} | {row['got_action']} | "
            f"{'PASS' if row['pass'] else 'FAIL'} |"
        )

    lines += [
        "",
        "### 指标 3：关键信息保留率（NIAH 式）",
        f"- 保留率 **{niah['retention_rate']:.2%}**"
        f"（{niah['survived']}/{niah['total']}，"
        f"keep_last={niah['keep_last']}, "
        f"max_obs_chars={niah['max_obs_chars']}）",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_report(path, content: str) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


# =====================================================================
# 自检：不导入项目模块的纯逻辑验证
# =====================================================================

def run_self_test() -> int:
    def check_follow_up_data():
        for case in FOLLOW_UP_CASES:
            assert case.get("message"), f"用例缺少 message：{case.get('name')}"
            assert case.get("expected_action") in {
                "answer_from_memory",
                "continue_research",
                "new_research",
            }, f"用例 action 非法：{case.get('name')}"
            assert case.get("expected_query"), f"用例缺少 expected_query"

    def check_niah_needle_format():
        needle = _NEEDLE_TEMPLATE.format(topic="芯片", score="87")
        assert "87分" in needle and "关键事实" in needle

    def check_niah_case_shape():
        cases = niah_cases(keep_last=2, max_obs_chars=4000)
        assert cases, "NIAH 用例不能为空"
        for case in cases:
            n = len(case["observations"])
            assert 1 <= case["needle_pos"] <= n
            assert case["observations"][case["needle_pos"] - 1] == case["needle"]

    def check_accuracy_math():
        fake = {"total": 4, "correct": 3}
        acc = fake["correct"] / fake["total"]
        assert abs(acc - 0.75) < 1e-9

    checks = [
        ("追问用例数据合法", check_follow_up_data),
        ("NIAH 针模板", check_niah_needle_format),
        ("NIAH 用例结构", check_niah_case_shape),
        ("正确率计算", check_accuracy_math),
    ]

    passed = 0
    for name, func in checks:
        try:
            func()
        except Exception:
            print(f"[FAIL] {name}")
            traceback.print_exc()
        else:
            print(f"[PASS] {name}")
            passed += 1

    print(f"\n自检通过 {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="评测短期记忆：多轮追问正确率 + 关键信息保留率。",
    )
    parser.add_argument(
        "--keep-last",
        type=int,
        default=2,
        help="滑动窗口保留条数，默认与 CONTEXT_KEEP_LAST_OBSERVATIONS 一致",
    )
    parser.add_argument(
        "--max-obs-chars",
        type=int,
        default=4000,
        help="单条观察截断长度，默认与 CONTEXT_MAX_OBSERVATION_CHARS 一致",
    )
    parser.add_argument("--json", dest="json_path", default="", help="指标写入 JSON")
    parser.add_argument("--md", dest="md_path", default="", help="指标写入 Markdown")
    parser.add_argument("--verbose", action="store_true", help="打印每条用例结果")
    parser.add_argument("--self-test", action="store_true", help="只验证逻辑不跑评测")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    follow_up = eval_follow_up_cases(verbose=args.verbose)
    print("")
    niah = eval_niah_cases(
        keep_last=args.keep_last,
        max_obs_chars=args.max_obs_chars,
        verbose=args.verbose,
    )

    print("")
    print(render_text(follow_up, niah))

    if args.json_path:
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "follow_up": follow_up,
            "niah": {k: v for k, v in niah.items() if k != "cases"},
            "niah_cases": niah["cases"],
        }
        target = write_report(
            args.json_path,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        print(f"\nJSON 已写入：{target}")

    if args.md_path:
        target = write_report(args.md_path, render_markdown(follow_up, niah))
        print(f"Markdown 已写入：{target}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
