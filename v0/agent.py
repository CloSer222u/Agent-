# -*- coding: utf-8 -*-
"""
agent.py —— Agent 最小雏形：整个项目真正的核心只有 run_agent() 这 40 行

【一句话定义 Agent】
Agent = 一个 while 循环，循环体里做三件事：
    ① 把「目前为止的全部对话」发给大模型
    ② 看模型的回复：是要调工具？还是要收工？
    ③ 调工具 → 把结果作为新消息「累加」进对话 → 回到 ①

对话列表（messages）只增不删，每一步都在「累加」，
这就是本项目名字「累加学习」的第一层含义；第二层含义是：
你以后每学一个概念，就往这个 Agent 上叠一个概念。

【运行方式】
  交互模式：  python agent.py
  单句模式：  python agent.py "帮我算一下 3 + 5 * 2"
  没有配 API Key 时会自动用 MockLLM，仍然能完整看到循环转起来。
"""

import json
import sys

import llm
from tools import TOOL_SCHEMAS, dispatch

# 系统提示词：每条对话的第一条消息，给模型定「人设 + 行为边界」。
# 它不是可选的装饰——它直接决定模型会不会主动用工具、用得好不好。
SYSTEM_PROMPT = (
    "你是一个能使用工具的小助手。"
    "回答前想一想：这个问题是否需要借助工具（计算、查时间、写笔记）。"
    "需要就调用工具，拿到结果后再用一两句话自然地总结回答；"
    "不需要就直接回答。不要编造工具才能给出的事实。"
)

MAX_STEPS = 8  # 安全阀：循环最多转 8 圈。没有它，模型可能无限调工具。


def run_agent(user_input, history):
    """核心循环。history 是累加的对话消息列表，跨轮次共享——
    这给了 Agent「本次会话的记忆」。（注意：history 会被原地修改）"""
    history.append({"role": "user", "content": user_input})

    for step in range(1, MAX_STEPS + 1):
        print("  [第 %d 圈] 正在把 %d 条消息发给模型…" % (step, len(history)))

        # ① 请求模型决策。messages 的 role 四种：
        #    system（人设）/ user（用户话）/ assistant（模型的过往动作，
        #    含它发起的工具调用）/ tool（工具的执行结果）
        msg = llm.chat(history, TOOL_SCHEMAS)

        tool_calls = msg.get("tool_calls")

        # —— 分支一：模型选择「继续干活」→ 返回了工具调用请求
        if tool_calls:
            # 关键步骤：先把模型这条「含 tool_calls 的消息」原样累加进 history。
            # 为什么？因为协议规定：下一条 role=tool 消息必须能和这条消息里
            # 的某个 tool_call_id 对上。跳过它，下一圈请求就会被 API 拒掉。
            history.append(msg)

            for call in tool_calls:                      # ② 我们替模型执行工具
                fn = call["function"]
                name = fn["name"]
                try:
                    args = json.loads(fn["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = fn["arguments"]               # dispatch 里再兜底报错
                print("         [模型动作] 调用工具 %s(%s)" % (name, args))
                result = dispatch(name, args)            # ③ 执行，拿到「观察」

                # ④ 把观察结果作为新消息累加，回给模型。
                #    tool_call_id 必须原样带回——这是「结果对应哪次调用」的信封编号。
                history.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": result,
                })
            continue                                     # 带着新增的消息，回到 ①

        # —— 分支二：模型选择「收工」→ 返回了纯文本回答
        answer = msg.get("content") or "（模型返回了空内容）"
        history.append({"role": "assistant", "content": answer})
        return answer

    # 循环转了 MAX_STEPS 圈还没收工：强制刹车，这也是 Agent 工程里
    # 最基本的「护栏」之一（预算控制）。
    return "已达到最大循环步数 %d，先停在这里（防止无限循环的保险丝）。" % MAX_STEPS


def main():
    # Windows 控制台可能是 GBK 编码，强行切 UTF-8 防乱码（老 Python 常见坑）
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # 单句模式：python agent.py "你的问题"
    if len(sys.argv) > 1:
        history = [{"role": "system", "content": SYSTEM_PROMPT}]
        print("你> %s" % sys.argv[1])
        print("Agent> %s" % run_agent(sys.argv[1], history))
        _dump_history(history)
        return

    # 交互模式：一个进程内持续累加 history —— 多轮记忆的雏形
    history = [{"role": "system", "content": SYSTEM_PROMPT}]
    print("Agent v0 雏形（输入 exit 退出，reset 清空记忆）")
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
            history = [{"role": "system", "content": SYSTEM_PROMPT}]
            print("Agent> 记忆已清空（history 重新初始化）。")
            continue
        print("Agent> %s" % run_agent(user_input, history))


def _dump_history(history):
    """退出时把完整对话打到屏幕上：亲眼确认「累加」发生过。"""
    print("\n──── 本次会话的完整消息累加记录（共 %d 条）────" % len(history))
    for i, m in enumerate(history):
        role = m["role"]
        if m.get("tool_calls"):
            names = [c["function"]["name"] for c in m["tool_calls"]]
            print("%02d [%-9s] 调用了工具: %s" % (i, role, names))
        else:
            text = (m.get("content") or "").replace("\n", " ")
            print("%02d [%-9s] %s" % (i, role, text[:80]))


if __name__ == "__main__":
    main()
