# -*- coding: utf-8 -*-
"""
agent.py（v2 版）—— 循环多了"分诊台"，其余骨架仍是 v1

与 v1 的 run_agent 逐段对照，只多了【错误处理】这一段。v1 是：

    现场错 → dispatch 把异常揉成 "ERROR:..." 字符串 → 直接当 Observation 回喂
    纸面错 → 固定话术 FORMAT_FIX → 回喂

v2 是：执行侧保留原始异常对象交给分诊台（triage），循环不再自己判断病情，
只执行分诊台开的三种动作之一：retry / reroute / wrap。

对应你 v2 预测里"根据级别进行重试"——级别在 triage.py，重试预算在 Book。

运行：
  python -X utf8 agent.py "算一下 3 + 5 * 2"        # 正常
  python -X utf8 agent.py "算一下 3 + 5 * 2 用V1_MOCK_CHAOS" 见 README 设环境变量
  演示四种病：见 README 的"故障演练场"
"""

import sys

import llm
import runner2
import triage
from protocol2 import SYSTEM_V2, parse_reply

MAX_STEPS = 8


def run_agent(user_input, history):
    book = triage.Book()                       # 处方记账本（可观测！）
    history.append({"role": "user", "content": user_input})

    for step in range(1, MAX_STEPS + 1):
        print("  [第 %d 圈] 发 %d 条消息，账本已吃 %d 张处方…" % (step, len(history), book.total))
        text = llm.chat_plain(history)
        history.append({"role": "assistant", "content": text})

        verdict = parse_reply(text)
        kind = verdict[0]

        if kind == "final":
            print("         [裁决] Final Answer，收工（共吃 %d 张处方）" % book.total)
            return verdict[1]

        # ── 分支 A：纸面错（还没碰工具）→ 格式病，直接分诊 ──
        if kind == "format_error":
            act, remedy = triage.prescribe(triage.FORMAT_DRIFT, book, verdict[1], True)
            print("         [裁决] 纸面错 → 处方[%s]" % act)
            history.append({"role": "user", "content": remedy})
            continue

        # ── 分支 B：模型发了 Action → 执行；执行可能现场报错 ──
        name, args = verdict[1], verdict[2]
        print("         [裁决] Action：%s(%s)" % (name, args))
        ok, out, exc, idempotent = runner2.run(name, args)   # ← 带回执的执行

        if ok:
            history.append({"role": "user", "content": "Observation: %s" % out})
            continue

        # 现场错：先回喂"事实"（失败也是观察，模型必须知道工具到底怎么了），
        # 再附上分诊台的"建议"（处方）。事实与建议分开——这是 v2 的核心改进，
        # 对比 v1 把两者混在一句 FORMAT_FIX 里。
        cls = triage.classify_runtime(exc, out)
        act, remedy = triage.prescribe(cls, book, out, idempotent)
        print("         [执行失败] 分诊=%s → 处方[%s]（幂等=%s）" % (cls, act, idempotent))
        history.append({"role": "user", "content": "Observation: ERROR: %s" % out})
        if act in ("retry", "reroute"):
            history.append({"role": "user", "content": remedy})
        else:  # wrap：预算用尽，下一圈逼模型 Final Answer 收工
            history.append({"role": "user", "content": remedy})

    return "已达到最大循环步数 %d，强制停止（硬保险丝，独立于处方软预算）。" % MAX_STEPS


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if len(sys.argv) > 1:
        history = [{"role": "system", "content": SYSTEM_V2}]
        print("你> %s" % sys.argv[1])
        print("Agent> %s" % run_agent(sys.argv[1], history))
        _dump(history)
        return

    history = [{"role": "system", "content": SYSTEM_V2}]
    print("Agent v2（错误分级自我修复；exit 看总账，reset 清记忆）")
    while True:
        try:
            user_input = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            _dump(history)
            break
        if user_input.lower() == "reset":
            history = [{"role": "system", "content": SYSTEM_V2}]
            print("Agent> 记忆已清空。")
            continue
        print("Agent> %s" % run_agent(user_input, history))


def _dump(history):
    rx = sum(1 for m in history if (m.get("content") or "").startswith("【处方"))
    print("\n──── 总账（%d 条，含 %d 张处方笺；处方都是 user 页=agent 代记的医嘱）────"
          % (len(history), rx))
    for i, m in enumerate(history):
        t = (m.get("content") or "").replace("\n", " ⏎ ")
        tag = " ⚠处方" if t.startswith("【处方】") else (" ⚠报错观察" if "ERROR" in t else "")
        print("%02d [%-9s]%s %s" % (i, m["role"], tag, t[:90]))


if __name__ == "__main__":
    main()
