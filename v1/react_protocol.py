# -*- coding: utf-8 -*-
"""
react_protocol.py —— v1 的灵魂：手写的「模型输出 ↔ 程序指令」契约

v0 里这个契约是 API 厂商替我们实现的（tools 参数 + tool_calls 字段）。
v1 把它撤掉，自己用「纯文本格式约定 + 解析器」重造一遍：

    约定模型只能输出两种形态：
        Thought: <一句想法>
        Action: 工具名[input: 参数]              ← 还要继续干活
    或者
        Thought: <一句想法>
        Final Answer: <给用户的话>               ← 收工

    我们负责：正则解析 → 执行 → 把结果写成
        Observation: <结果>
    塞回对话（注意：v1 里已经没有 role="tool" 了，Observation 只能
    借 role="user" 的嘴说——这是手写协议的第一处「寒酸」）。

解析失败怎么办？不发火、不崩溃，而是把「格式错误说明」作为一条
user 消息喂回去，让模型重写——这是 v2 错误处理思想的种子。
"""

import os
import re
import sys

# ── 复用 v0 的工具层：v1 只换「决策协议」，工具本体零改动 ──
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "v0"))
from tools import TOOL_IMPLS  # noqa: E402  名字→函数 的注册表（含护栏）

# 每个工具在文本协议里接受的参数名（和 v0 schema 保持一致的 mini 版）
TOOL_ARGS = {
    "calculator": ["expression"],
    "get_time": [],
    "write_note": ["filename", "content"],
}

_ACTION_RE = re.compile(r"^\s*Action:\s*(\S+)\s*\[(.*)\]\s*$", re.M)
_FINAL_RE = re.compile(r"^\s*Final Answer:\s*(.+)$", re.M)

# 系统提示词：v0 的人设 + 「说明书」现在以自然语言写进 prompt 本身。
# v0 里说明书住在 payload 的 tools 字段；v1 里它只能住在文字里——
# 对比两边，你会真切感到 function calling 替你扛下了什么。
SYSTEM_REACT = (
    "你是一个会用工具的助手，严格按以下两种格式之一回复，不要输出别的内容：\n\n"
    "格式一（需要查东西时）：\n"
    "Thought: 你为什么需要工具\n"
    "Action: 工具名[input: 参数]\n"
    "之后我会以 Observation: 开头的消息告诉你工具结果，你继续用同样的格式回复。\n\n"
    "格式二（有把握给出最终回答时）：\n"
    "Thought: 你已经拿到全部需要的信息\n"
    "Final Answer: 给用户的完整回答\n\n"
    "可用工具：\n"
    "- calculator[input: 算术表达式]，例如 Action: calculator[input: 3 + 5 * 2]\n"
    "- get_time[]，无参数，例如 Action: get_time[]\n"
    "- write_note[input: filename=文件名 | content=正文]，写一条笔记文件\n"
)

# 解析失败时替用户说的那句「格式纠正指令」
FORMAT_FIX = (
    "你的上一条回复不符合格式要求：%s。"
    "请重新输出，二选一：Action: 工具名[input: ...] 或 Final Answer: ..."
)


def parse_reply(text):
    """把模型的一段原始文本裁决成三种结果之一。

    返回 ("final", 答案文本) / ("action", 工具名, 参数字典) / ("format_error", 原因)
    裁决顺序是有意设计的：Final Answer 优先于 Action（模型有时两个都说，
    说了「可以给最终答案」就信它收工）。
    """
    m = _FINAL_RE.search(text)
    if m:
        return ("final", m.group(1).strip())

    m = _ACTION_RE.search(text)
    if not m:
        return ("format_error", "既没有 Action 行也没有 Final Answer 行")
    name, interior = m.group(1), m.group(2)

    # 工具名幻觉拦截（v0 里 dispatch 也有同款兜底，这里提前给格式反馈）
    if name not in TOOL_IMPLS:
        return ("format_error", "工具 %s 不存在，可选：%s" % (name, list(TOOL_IMPLS)))

    expected = TOOL_ARGS[name]
    if not expected:
        # 无参工具：[] 内必须是空白
        if interior.strip() == "":
            return ("action", name, {})
        return ("format_error", "%s 是无参工具，应写作 %s[]" % (name, name))

    # 有参工具：必须形如 input: ...
    if not interior.startswith("input:"):
        return ("format_error", "缺少 input: 前缀（%s 需要参数 %s）" % (name, expected))
    payload = interior[len("input:"):].strip()

    if len(expected) == 1:
        # 单参工具（calculator）：整段 payload 就是参数值
        return ("action", name, {expected[0]: payload})

    # 多参工具（write_note）：约定 k=v 用「 | 」分隔
    args = {}
    for part in payload.split("|"):
        if "=" not in part:
            return ("format_error", "参数片段 %r 不是 k=v 形式" % part.strip())
        k, v = part.split("=", 1)
        args[k.strip()] = v.strip()
    missing = [k for k in expected if k not in args]
    if missing:
        return ("format_error", "缺少参数 %s" % missing)
    return ("action", name, {k: args[k] for k in expected})


def build_observation(result_text):
    """把工具输出包装成回喂消息的文本。v1 没有 tool role，只能拼字符串。"""
    return "Observation: %s" % result_text
