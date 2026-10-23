# -*- coding: utf-8 -*-
"""
llm.py（v3 版）—— 真调用通道不变；Mock 改用"命名空间谓词"认插话

对比 v2 的 Mock：甄别插话从"三种前缀各写各的黑名单"
换成 `memory.is_note(m)` 一个谓词 + `note_kind(m)` 分发。
v2 那两个 bug（【处方· 前缀没命中、旧处方未消化）在这个结构下
一个不可能发生（前缀只有一处定义），一个仍会发生——
提醒：命名空间治"认不出插话"，不治"插话已消化"，那是状态问题不是格式问题。
"""

import json
import os
import re
import urllib.error
import urllib.request

from memory import is_note, note_kind

BASE_URL = os.environ.get("AGENT_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL = os.environ.get("AGENT_MODEL", "qwen-plus")
API_KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()
CHAOS = os.environ.get("V1_MOCK_CHAOS") == "1"
STUBBORN = os.environ.get("V2_MOCK_STUBBORN") == "1"


def chat_plain(messages):
    if API_KEY:
        return _real_chat(messages)
    print("[llm] 无 DASHSCOPE_API_KEY，使用 v3 Mock。")
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
    # 真问题 = 最后一条"非插话"的 user 消息（一个谓词搞定）
    q_idx, q = -1, ""
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("role") == "user" and not is_note(m):
            q_idx, q = i, m["content"]
            break

    window = messages[q_idx:]
    last_a = -1
    for i in range(len(window) - 1, -1, -1):
        if window[i].get("role") == "assistant":
            last_a = i
            break
    after = window[last_a + 1:]

    def kind_contents(kind, pred=None):
        out = []
        for m in after:
            if note_kind(m) == kind:
                c = m["content"]
                if pred is None or pred(c):
                    out.append(c)
        return out

    oks = kind_contents("观察", lambda c: "ERROR" not in c)
    rxs = kind_contents("处方")
    rem = rxs[-1] if rxs else ""
    errors = [m["content"] for m in window
              if note_kind(m) == "观察" and "ERROR" in m["content"]]

    # 摘要页存在=旧账被归档过；Mock 只演示"承认摘要、不重做已完成操作"
    seen_digest = any(note_kind(m) == "摘要" for m in messages)

    if oks:
        joined = "；".join(c.split("〕", 1)[-1].replace("Observation:", "").strip() for c in oks)
        extra = "（注：旧对话已归档在摘要页，我据此续接，没有重做完成过的操作。）" if seen_digest else ""
        return ("Thought: 拿到结果了，收工。\nFinal Answer: 任务完成，结果是：%s。%s"
                "（Mock 复述；真模型会组织成自然语言。）" % (joined, extra))

    if rem and any(k in rem for k in ("预算用尽", "禁止自动重试", "换一种做法")):
        why = errors[-1].split("〕", 1)[-1][len("ERROR: "):] if errors else rem[:40]
        return ("Thought: 处方叫停，不再撞墙，如实收工。\n"
                "Final Answer: 这个任务没能完成：%s。我已按处方停止重试，未造成额外副作用。" % why)
    if rem and "修正参数" in rem:
        return ("Thought: 参数病且幂等，换合法参数重试。\n"
                "Action: calculator[input: 3 + 1]")
    if rem and "改写" in rem:
        m = re.search(r"[-+*/%()\d\.\s]{3,}", q)
        expr = m.group(0).strip() if m else "3 + 5 * 2"
        if STUBBORN:
            return "Thought: （顽固模式）我还是想这么写。\nAction: calculator[%s]" % expr
        return ("Thought: 工具没执行过，改写安全，保持原意重写。\n"
                "Action: calculator[input: %s]" % expr)

    # 新发起动作（问题驱动规则与 v2 相同）
    if "打卡" in q:
        return "Thought: 打卡是非幂等工具。\nAction: stamp_clock[input: 上班]"
    if "坏" in q:
        return "Thought: 按剧本发一个会现场报错的调用。\nAction: calculator[input: 1/0]"
    if "护栏" in q:
        return "Thought: 按剧本撞一次护栏。\nAction: calculator[input: 9**99]"
    m = re.search(r"[-+*/%()\d\.\s]{3,}", q)
    if (re.search(r"算|计算", q) or re.search(r"\d.*[+\-*/].*\d", q)) and m:
        expr = m.group(0).strip()
        tried = any((mm.get("content") or "").find("Action:") >= 0
                    for mm in window if mm.get("role") == "assistant")
        if (CHAOS or STUBBORN) and not tried:
            return "Thought: 需要计算器。\nAction: calculator[%s]" % expr
        return "Thought: 算术题，用计算器。\nAction: calculator[input: %s]" % expr
    if re.search(r"笔记|记下|保存|写到", q):
        return ("Thought: 保存内容用 write_note。\n"
                "Action: write_note[input: filename=mock_note.txt | content=%s]" % q)
    if re.search(r"几点|时间|日期|今天|星期", q):
        return "Thought: 我无状态，需要时间工具。\nAction: get_time[]"
    return "Thought: 不需要工具。\nFinal Answer: （Mock 兜底）收到：%s" % q
