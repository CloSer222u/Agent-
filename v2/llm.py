# -*- coding: utf-8 -*-
"""
llm.py（v2 版）—— 纯文本通道不变；Mock 升级成「会读处方笺的假模型」

真实调用与 v1 完全相同（撤掉 tools 的纯聊天）。变化全在 Mock：
它现在要模仿"一个会自我修复的模型"读到【处方】后的四种行为——
  1) 处方说"修正参数重试"   → 换个参数再发 Action（演示现场病·可修复）
  2) 处方说"改写格式"        → 原意不变重写 Action；STUBBORN 模式则屡教不改
  3) 处方说"禁止重试/换招/收工"→ 老实 Final Answer，绝不撞第二次墙
  4) 成功观察到手            → 复述收工（v1 规则）

环境变量：
  V1_MOCK_CHAOS=1     第一次算术动作格式漂移（纸面病演示）
  V2_MOCK_STUBBORN=1  屡教不改（预算耗尽→优雅收工演示）
"""

import json
import os
import re
import urllib.error
import urllib.request

BASE_URL = os.environ.get("AGENT_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL = os.environ.get("AGENT_MODEL", "qwen-plus")
API_KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()
CHAOS = os.environ.get("V1_MOCK_CHAOS") == "1"
STUBBORN = os.environ.get("V2_MOCK_STUBBORN") == "1"

# 甄别"真问题"时要跳过的三种插话（全是用户角色，全靠前缀认人——
# "借 user 的嘴"插话的甄别成本，到这里要连本带利还）
_SKIP_PREFIX = ("Observation:", "【处方", "你的上一条回复")


def chat_plain(messages):
    if API_KEY:
        return _real_chat(messages)
    print("[llm] 无 DASHSCOPE_API_KEY，使用 v2 Mock（会读处方笺的假模型）。")
    return _mock_chat(messages)


def _real_chat(messages):
    payload = {"model": MODEL, "messages": messages}
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
    return body["choices"][0]["message"].get("content") or ""


def _mock_chat(messages):
    q_idx, q = -1, ""
    for i in range(len(messages) - 1, -1, -1):
        c = messages[i].get("content") or ""
        if messages[i].get("role") == "user" and not c.startswith(_SKIP_PREFIX):
            q_idx, q = i, c
            break
    window = messages[q_idx:]

    # 「未消化」= 最后一条 assistant 之后的消息。模型（Mock）上一条说完后，
    # agent 追加了什么，它就欠着什么：成功观察 or 处方。上一条 assistant
    # 之前的旧处方已经执行过了，再照办就成了上一版 bug：无限重试不领工。
    last_a = -1
    for i in range(len(window) - 1, -1, -1):
        if window[i].get("role") == "assistant":
            last_a = i
            break
    after = window[last_a + 1:]
    oks = [m["content"] for m in after if (m.get("content") or "").startswith("Observation:")
           and "ERROR" not in m["content"]]
    rems = [m["content"] for m in after if (m.get("content") or "").startswith("【处方")]
    rem = rems[-1] if rems else ""
    errors = [m["content"] for m in window
              if (m.get("content") or "").startswith("Observation: ERROR")]
    tried = any((m.get("content") or "").find("Action:") >= 0
                for m in window if m.get("role") == "assistant")

    # 优先级 1：手上有成功结果 → 收工（先于处方！旧处方已被那条 Action 消化）
    if oks:
        joined = "；".join(o[len("Observation: "):].strip() for o in oks)
        return ("Thought: 拿到结果了，收工。\nFinal Answer: 任务完成，结果是：%s。"
                "（Mock 复述；真模型会组织成自然语言。）" % joined)

    # 优先级 2：有未消化的处方 → 按处方处置（顺序：叫停 > 改参 > 改写）
    if rem and any(k in rem for k in ("预算用尽", "禁止自动重试", "换一种做法")):
        why = errors[-1][len("Observation: "):] if errors else rem[:40]
        return ("Thought: 处方明确叫停，我不再撞墙，如实收工。\n"
                "Final Answer: 这个任务没能完成：%s。我已按处方停止重试，"
                "没有造成额外副作用（非幂等工具未被重复执行）。" % why)
    if rem and "修正参数" in rem:
        return ("Thought: 处方说是参数病且工具幂等，换一个合法参数重试。\n"
                "Action: calculator[input: 3 + 1]")
    if rem and "改写" in rem:
        m = re.search(r"[-+*/%()\d\.\s]{3,}", q)
        expr = m.group(0).strip() if m else "3 + 5 * 2"
        if STUBBORN:  # 屡教不改演示：原样再漂一次，直到预算用尽
            return "Thought: （顽固模式）我还是想这么写。\nAction: calculator[%s]" % expr
        return ("Thought: 处方说工具没执行过，改写绝对安全，保持原意重写。\n"
                "Action: calculator[input: %s]" % expr)

    # 优先级 3：手上没货，按问题发起新动作

    # 问题驱动的演示触发词
    if "打卡" in q:
        return ("Thought: 用户要打卡，这是非幂等工具，结果不确定时不可重试。\n"
                "Action: stamp_clock[input: 上班]")
    if "坏" in q:
        return ("Thought: 按演示剧本发一个会现场报错的调用。\n"
                "Action: calculator[input: 1/0]")
    if "护栏" in q:
        return ("Thought: 按演示剧本发一个撞护栏的调用。\n"
                "Action: calculator[input: 9**99]")
    m = re.search(r"[-+*/%()\d\.\s]{3,}", q)
    if (re.search(r"算|计算", q) or re.search(r"\d.*[+\-*/].*\d", q)) and m:
        expr = m.group(0).strip()
        if (CHAOS or STUBBORN) and not tried:
            return "Thought: 需要计算器。\nAction: calculator[%s]" % expr
        return ("Thought: 算术题，用计算器。\nAction: calculator[input: %s]" % expr)
    if re.search(r"笔记|记下|保存|写到", q):
        return ("Thought: 保存内容用 write_note。\n"
                "Action: write_note[input: filename=mock_note.txt | content=%s]" % q)
    if re.search(r"几点|时间|日期|今天|星期", q):
        return "Thought: 我无状态，需要时间工具。\nAction: get_time[]"
    return "Thought: 不需要工具。\nFinal Answer: （Mock 兜底）收到：%s" % q
