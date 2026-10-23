# -*- coding: utf-8 -*-
"""
llm.py（v4 版）—— Mock 新增"查旧账三步舞"，演示 Agentic 检索节奏

触发词：旧账/上次/之前/档案 → search_kb；
拿到命中且要求原文 → read_page(最佳命中页号)；
读到原文或 0 命中 → 收尾引用。
真模型不需要这套规则——它自己决定何时调哪个，这正是
"Agentic RAG vs 管线 RAG"的对照点（见 README 设计要点）。
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
    print("[llm] 无 DASHSCOPE_API_KEY，使用 v4 Mock。")
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
        m = messages[i]
        if m.get("role") == "user" and not is_note(m):
            q_idx, q = i, m["content"]
            break
    window = messages[q_idx:] if q_idx >= 0 else messages
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

    oks = kind_contents("观察")
    rxs = kind_contents("处方")
    rem = rxs[-1] if rxs else ""

    hits = [c for c in oks if "检索结果：" in c and "0 命中" not in c]
    got0 = [c for c in oks if "0 命中" in c]
    fulls = [c for c in oks if c.split("〕", 1)[-1].startswith("[assistant]")
             or c.split("〕", 1)[-1].startswith("[user]")]
    tried = any("Action:" in (m.get("content") or "") for m in window
                if m.get("role") == "assistant")
    called_search = any("search_kb" in (m.get("content") or "") for m in window
                        if m.get("role") == "assistant")
    called_read = any("read_page" in (m.get("content") or "") for m in window
                      if m.get("role") == "assistant")

    # ── 优先级 1：待执行的处方（同 v3）──
    if rem and any(k in rem for k in ("预算用尽", "禁止自动重试", "换一种做法")):
        return ("Thought: 处方叫停，如实收工。\nFinal Answer: 这个任务没能完成：%s。"
                % (rem.split("】", 1)[-1][:60] if "】" in rem else rem[:60]))
    if rem and "修正参数" in rem:
        return ("Thought: 参数病且幂等，换合法参数重试。\n"
                "Action: calculator[input: 3 + 1]")
    if rem and "改写" in rem:
        m = re.search(r"[-+*/%()\d\.\s]{3,}", q)
        expr = m.group(0).strip() if m else "3 + 5 * 2"
        if STUBBORN:
            return "Thought: （顽固模式）我还是想这么写。\nAction: calculator[%s]" % expr
        return ("Thought: 改写安全，保持原意重写。\n"
                "Action: calculator[input: %s]" % expr)

    # ── 优先级 2：查旧账三步舞 ──
    if called_search and hits and not called_read:
        pid = re.search(r"[\w.\-]+\.jsonl#L\d+", hits[-1])
        if pid:
            return ("Thought: 命中里有页号，要原文就得二拍取页（线索→取全文的定式）。\n"
                    "Action: read_page[input: %s]" % pid.group(0))
    if called_read and fulls:
        body = fulls[-1].split("〕", 1)[-1]
        return ("Thought: 原文取到了，引用收尾。\n"
                "Final Answer: 旧账查到了，原文如下：%s（Mock 直引；真模型会总结复述。）"
                % body[:150])
    if called_search and got0 and not called_read:
        # 重试纪律两条闸：① 计数必须按"本轮全部观察"算——之前按 after
        # （上一 assistant 之后）算，每轮看到的永远是 1 条，纪律形同虚设
        # （实测翻车）。② 换词必须真换得出：核心词已无可剥时，直接如实收工。
        win0 = [m for m in window if note_kind(m) == "观察" and "0 命中" in m["content"]]
        m3 = re.search(r"[：:]\s*(.+)$", q)
        base = m3.group(1) if m3 else q
        base = re.sub(r"(原文|全文|是什么)的?$", "", base)
        if len(win0) == 1 and len(base) > 6:
            return ("Thought: 零命中，剥掉请求套话，换更窄的核心词再试一次。\n"
                    "Action: search_kb[input: %s]" % base[:6])
    if called_search and (hits or got0):
        joined = "；".join(c.split("〕", 1)[-1][:120] for c in (hits or got0))
        return ("Thought: 检索线索足够，直接收工。\n"
                "Final Answer: 旧账检索结果：%s" % joined)

    # ── 优先级 3：新发起动作 ──
    if re.search(r"旧账|档案|上次|之前", q) and not tried:
        m2 = re.search(r"[：:]\s*(.+)$", q)
        kw = m2.group(1) if m2 else q
        return ("Thought: 这是查长期记忆，当前窗口里没有，得检索档案。\n"
                "Action: search_kb[input: %s]" % kw[:24])
    if oks:
        joined = "；".join(c.split("〕", 1)[-1].strip() for c in oks)
        return ("Thought: 拿到结果了，收工。\nFinal Answer: 任务完成，结果是：%s。"
                "（Mock 复述。）" % joined)

    # 其余问题驱动规则与 v3 相同
    if "打卡" in q:
        return "Thought: 打卡是非幂等工具。\nAction: stamp_clock[input: 上班]"
    if "坏" in q:
        return "Thought: 按剧本发一个会现场报错的调用。\nAction: calculator[input: 1/0]"
    if "护栏" in q:
        return "Thought: 按剧本撞一次护栏。\nAction: calculator[input: 9**99]"
    m = re.search(r"[-+*/%()\d\.\s]{3,}", q)
    if (re.search(r"算|计算", q) or re.search(r"\d.*[+\-*/].*\d", q)) and m:
        expr = m.group(0).strip()
        if (CHAOS or STUBBORN) and not tried:
            return "Thought: 需要计算器。\nAction: calculator[%s]" % expr
        return "Thought: 算术题，用计算器。\nAction: calculator[input: %s]" % expr
    if re.search(r"笔记|记下|保存|写到", q):
        return ("Thought: 保存内容用 write_note。\n"
                "Action: write_note[input: filename=mock_note.txt | content=%s]" % q)
    if re.search(r"几点|时间|日期|今天|星期", q):
        return "Thought: 我无状态，需要时间工具。\nAction: get_time[]"
    return "Thought: 不需要工具。\nFinal Answer: （Mock 兜底）收到：%s" % q
