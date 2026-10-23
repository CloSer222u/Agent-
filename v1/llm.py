# -*- coding: utf-8 -*-
"""
llm.py（v1 版）—— 大脑接口退化为「纯聊天」：只收发文本

对比 v0 的 llm.py，本文件只有三处不同，这正是 v1 的全部改动面：
  1. payload 里不再有 tools / tool_choice 字段（协议撤销）；
  2. 返回值不再是 message 字典，而是 assistant 消息里的纯文本 str；
  3. Mock 不再返回 tool_calls JSON，而是模仿模型「吐 ReAct 格式文本」，
     并且可以故意吐错格式（环境变量 V1_MOCK_CHAOS=1）来逼你调解析器。

其余（无状态、全量重发 messages、Authorization 头）与 v0 完全相同——
体会一下：换协议 = 换「说辞的格式」，请求的本质没变。
"""

import json
import os
import re
import urllib.error
import urllib.request

BASE_URL = os.environ.get("AGENT_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL = os.environ.get("AGENT_MODEL", "qwen-plus")
API_KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()
CHAOS = os.environ.get("V1_MOCK_CHAOS") == "1"   # Mock 故意捣乱模式


def chat_plain(messages):
    """发一次纯文本聊天请求，返回模型回复的原始文本（str）。"""
    if API_KEY:
        return _real_chat(messages)
    print("[llm] 未检测到 DASHSCOPE_API_KEY，使用 MockReAct（会吐 ReAct 文本的假模型）。")
    return _mock_chat(messages)


def _real_chat(messages):
    payload = {"model": MODEL, "messages": messages}   # ← 对比 v0：没有 tools 字段了
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + API_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:400]))
    msg = body["choices"][0]["message"]
    # 有的模型偶尔回 None（比如被截断），兜底成空串让解析器报格式错误
    return msg.get("content") or ""


# ══════════════════════════════════════════════
# MockReAct：用规则模仿「会吐 ReAct 文本」的模型
# ══════════════════════════════════════════════
# 会话里 user 角色有两种：真用户提问、以及我们代发的 "Observation:" 消息。
# Mock 要先把两者区分开，才能知道「本轮的问题是什么、结果到没到」。
def _mock_chat(messages):
    question_idx = -1
    question = ""
    for i in range(len(messages) - 1, -1, -1):
        c = messages[i].get("content") or ""
        # 跳过「Observation」和「格式纠正指令」——它们不是真问题。
        # （真模型能分清这点是因为它有语义理解，Mock 只能人肉列前缀黑名单。
        #  上一版本没跳过纠正指令，结果把指令当成了新问题——v1 实测抓到的 bug。）
        if (messages[i].get("role") == "user"
                and not c.startswith("Observation:")
                and not c.startswith("你的上一条回复不符合格式要求")):
            question_idx, question = i, c
            break
    observations = [m["content"] for m in messages[question_idx:]
                    if (m.get("content") or "").startswith("Observation:")]

    # 规则 A：本轮已有观察结果 → 收工（Final Answer 分支）
    if observations:
        joined = "；".join(o[len("Observation:"):].strip() for o in observations)
        return "Thought: 工具已经把结果交给我了，可以给出最终回答。\n" \
               "Final Answer: 任务完成，工具查到的结果是：%s。（Mock 只会复述；" \
               "真模型会把 Observation 组织成自然语言。）" % joined

    # 本轮是否已经发起过 Action？（决定 CHAOS 只坏「第一次」）
    already_tried = any((m.get("content") or "").find("Action:") >= 0
                        for m in messages[question_idx:] if m.get("role") == "assistant")

    # 规则 B：算术 → calculator
    m = re.search(r"[-+*/%()\d\.\s]{3,}", question)
    if re.search(r"算|计算|\d.*[+\-*/].*\d", question) and m:
        expr = m.group(0).strip()
        if CHAOS and not already_tried:
            # 第一次故意吐错格式（漏 input: 前缀）模拟「格式漂移」，
            # 被纠正后改吐正确格式——模仿真模型「读指令、守格式」的行为。
            return "Thought: 需要计算器。\nAction: calculator[%s]" % expr
        return "Thought: 这是一个算术题，我不能心算，需要工具。\n" \
               "Action: calculator[input: %s]" % expr

    # 规则 C：笔记 → write_note
    if re.search(r"笔记|记下|保存|写到", question):
        m2 = re.search(r"[：:]\s*(.+)$", question)
        body = m2.group(1) if m2 else question
        return "Thought: 用户要我保存内容，用 write_note。\n" \
               "Action: write_note[input: filename=mock_note.txt | content=%s]" % body

    # 规则 D：时间 → get_time
    if re.search(r"几点|时间|日期|今天|星期", question):
        return "Thought: 我无状态、不报时，需要看时间工具。\nAction: get_time[]"

    # 规则 E：兜底 → 直接给最终回答
    return "Thought: 这个问题不需要工具。\nFinal Answer: （Mock 兜底）收到：%s" % question
