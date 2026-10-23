# -*- coding: utf-8 -*-
"""
memory.py —— v3 的新器官：记忆管理（记录账 ≠ 发送账）

三件事，对应本版本的三个关键词：

 1) SessionLog  **落盘**：每记一页账，同时往 JSONL 文件写一行。
    记录账从此不随进程死亡。注意用的是 "a" 追加模式——
    v2 生词卡说的"非幂等的物理来源"，这次用在自己的账本上。
 2) sent_view   **瘦身**：发送前给账本估体积，超预算就只寄
    "system + 摘要页 + 最近窗口"。记录账全量保留，发送账分家——
    v2→v3 预告锚点里那句"记录账≠发送账"，在此实现。
 3) note()      **插话命名空间**：v1 起借 user 的嘴，甄别靠
    三四种前缀黑名单（v2 开发 bug 的根因之一）。v3 统一为
    〔插话·种类〕一个前缀——甄别从"黑名单"降为"一个谓词"。
"""

import json
import os
import re
from collections import Counter

NOTE_MARK = "〔插话"


# ── 命名空间三件套 ─────────────────────────────
def note(kind, text):
    """把 agent 代记的插话统一包装：kind ∈ {观察, 处方, 摘要}"""
    return NOTE_MARK + "·" + kind + "〕" + text


def is_note(m):
    """唯一的甄别谓词——v1/v2 那串前缀黑名单退役。"""
    return m.get("role") == "user" and (m.get("content") or "").startswith(NOTE_MARK)


def note_kind(m):
    c = m.get("content") or ""
    mt = re.match(r"〔插话·([^〕]+)〕", c)
    return mt.group(1) if mt else None


# ── 落盘：会话 JSONL ───────────────────────────
class SessionLog(object):
    """一页 = 一行 JSON。文件长出来的顺序就是账本的顺序（账本只追加的物理兑现）。"""

    def __init__(self, path):
        self.path = path
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)

    def write(self, msg):
        # 每条消息单独一行、单独一次 "a" 追加：进程中途被杀，已记的页也在
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    @staticmethod
    def load(path):
        """恢复账本：坏行跳过不崩。返回 (找回的页, 被跳过的行数)。

        三道安检，对应三种真实脏法：
          空行（手工编辑残留/行尾换行）      -> continue 静默跳
          语法坏（进程被杀在写一半的瞬间）    -> 计一次跳过，**报告**，不崩
          语法对但不是消息（{"foo":1}、[1,2]） -> 同上报跳——后面所有代码都
            假设有 role/content 两键，放进半页怪账，炸的是整次对话。
        跳过数要如实带回，因为"内存账+跳行=档案行"这条对照公式要用它。
        """
        msgs, skipped = [], 0
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    m = json.loads(line)
                except ValueError:
                    skipped += 1
                    print("[恢复] 跳过损坏的第 %d 行：%s" % (i, line[:40]))
                    continue
                if isinstance(m, dict) and "role" in m and "content" in m:
                    msgs.append(m)
                else:
                    skipped += 1
                    print("[恢复] 跳过非法消息形态的第 %d 行：%s" % (i, line[:40]))
        return msgs, skipped


# ── 体积的尺子 ─────────────────────────────────
def estimate(pages):
    """近似体积：字符数。真实系统用 tokenizer 精确计 token——
    近似体积与精确 token 概念等价，真实系统换 tokenizer 只动本函数。"""
    return sum(len(m.get("content") or "") for m in pages)


# ── 摘要器：给被归档的旧页写一份"案卷封面" ────
def digest(dropped):
    """确定性规则摘要（Mock 用）。真实系统可把这页丢给模型自己写——
    同一个接口，两种实现，v2 Mock 教过的老套路。"""
    qs = [m["content"] for m in dropped
          if m.get("role") == "user" and not is_note(m)]
    acts = re.findall(r"Action:\s*(\w+)",
                      "\n".join((m.get("content") or "") for m in dropped
                                if m.get("role") == "assistant"))
    rxs = sum(1 for m in dropped if note_kind(m) == "处方")
    finals = [(m.get("content") or "").split("Final Answer:")[-1].strip()
              for m in dropped
              if m.get("role") == "assistant" and "Final Answer:" in (m.get("content") or "")]
    tools = "、".join("%s×%d" % (k, v) for k, v in Counter(acts).items()) or "无"
    return ("已归档 %d 页。提问 %d 个（首问：%s｜近问：%s）；工具执行 %s；"
            "处方 %d 张；最近结论：%s"
            % (len(dropped), len(qs),
               (qs[0][:20] if qs else "-"), (qs[-1][:20] if qs else "-"),
               tools, rxs, (finals[-1][:30] if finals else "-")))


# ── 发送视图：记录账 → 发送账的变形函数 ────────
def sent_view(history, budget_chars):
    """返回 (寄出去的页列表, 被归档的页数)。

    两条铁律：
      ① 系统页永不裁剪（法条不废）；
      ② 合法切口必须是"真用户提问"——绝不从插话/观察中间切，
         切在回合边界上，模型读到的永远是完整回合。
         （若走 v0 的 tool_calls 协议，切口还必须落在配对之外——
          这是 ReAct 账本对截断更宽容的原因之一。）
    """
    if estimate(history) <= budget_chars:
        return list(history), 0

    head = history[0:1]                      # system
    body = history[1:]
    size = len((head[0].get("content") or "")) + 150   # 预留摘要页的体积
    kept = []
    for m in reversed(body):
        c = m.get("content") or ""
        if kept and size + len(c) > budget_chars:
            break
        kept.insert(0, m)
        size += len(c)

    # 铁律②：把窗口开头向前推到最近的"真提问"
    while len(kept) > 2 and is_note(kept[0]):
        kept.pop(0)

    n_drop = len(body) - len(kept)
    if n_drop <= 0:
        return list(history), 0
    dropped = body[:n_drop]
    return head + [ {"role": "user", "content": note("摘要", digest(dropped))} ] + kept, n_drop
