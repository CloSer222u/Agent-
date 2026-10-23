# -*- coding: utf-8 -*-
"""
agent.py（v1 版）—— ReAct 循环：协议从 API 借来的，现在自己手写

和 v0 的 run_agent 逐段对照着读，差异只有三处（都被注释标出）：

  v0                              v1
  llm.chat 返回 message 字典       llm.chat_plain 返回纯文本
  if msg["tool_calls"] 结构化字段   parse_reply(text) 正则裁决
  tool 消息 role="tool" + id       借 role="user" 说 "Observation: …"

循环骨架（累加、continue、MAX_STEPS 保险丝）一字未动——
这就是路线图说的「每阶段只叠一个概念」。

运行：
  python -X utf8 agent.py "帮我算一下 3 + 5 * 2"
  python -X utf8 agent.py                      （交互，exit 看总账）
  $env:V1_MOCK_CHAOS="1" 后运行 → Mock 第一轮故意吐错格式，
  观察解析器如何把「格式纠正指令」喂回去让模型重写。
"""

import sys

import llm
from react_protocol import (
    FORMAT_FIX,
    SYSTEM_REACT,
    build_observation,
    parse_reply,
)
from tools import dispatch  # 来自 v0 目录（react_protocol 已把路径加好）

MAX_STEPS = 8


def run_agent(user_input, history):
    history.append({"role": "user", "content": user_input})

    for step in range(1, MAX_STEPS + 1):
        print("  [第 %d 圈] 正在把 %d 条消息发给模型…" % (step, len(history)))
        text = llm.chat_plain(history)                    # ← 差异 1：只要文本
        # 模型的原始文本也要落账（v0 由 API 代记，v1 我们亲手记——
        # 注意：落账的是「它原话」，解析动作不修改原文，这保证账本可回放）
        history.append({"role": "assistant", "content": text})

        verdict = parse_reply(text)                       # ← 差异 2：自己裁决
        kind = verdict[0]

        if kind == "final":
            answer = verdict[1]
            print("         [裁决] Final Answer 分支，收工")
            return answer

        if kind == "action":
            name, args = verdict[1], verdict[2]
            print("         [裁决] Action：%s(%s)" % (name, args))
            result = dispatch(name, args)
            obs = build_observation(result)
            print("         [回喂] %s" % obs[:80])
            # ← 差异 3：没有 role="tool"，没有 tool_call_id，
            #   观察结果只能作为一条 user 文本消息回到模型眼前
            history.append({"role": "user", "content": obs})
            continue

        # kind == "format_error"：模型没守住格式约定。
        # 不发火、不崩溃——把错误原因写成一条指令消息喂回去，让它重写。
        reason = verdict[1]
        print("         [裁决] 格式错误：%s → 已回喂纠正指令" % reason)
        history.append({"role": "user", "content": FORMAT_FIX % reason})
        continue

    return "已达到最大循环步数 %d，强制停止（保险丝）。" % MAX_STEPS


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if len(sys.argv) > 1:
        history = [{"role": "system", "content": SYSTEM_REACT}]
        print("你> %s" % sys.argv[1])
        print("Agent> %s" % run_agent(sys.argv[1], history))
        _dump_history(history)
        return

    history = [{"role": "system", "content": SYSTEM_REACT}]
    print("Agent v1（ReAct 手写协议；exit 看总账，reset 清记忆）")
    while True:
        try:
            user_input = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            _dump_history(history)
            break
        if user_input.lower() == "reset":
            history = [{"role": "system", "content": SYSTEM_REACT}]
            print("Agent> 记忆已清空。")
            continue
        print("Agent> %s" % run_agent(user_input, history))


def _dump_history(history):
    print("\n──── 本次会话消息总账（共 %d 条，只有 system/user/assistant 三种角色）────"
          % len(history))
    for i, m in enumerate(history):
        text = (m.get("content") or "").replace("\n", " ⏎ ")
        print("%02d [%-9s] %s" % (i, m["role"], text[:90]))


if __name__ == "__main__":
    main()
