# -*- coding: utf-8 -*-
"""
agent.py（v4 版）—— 循环长到第五版，唯一的改动：手术刀换了个插座

对比 v3 的 agent.py，本文件只有一处实质变化：
  dispatch 从 runner2.run 换成 tools4.run4
  （新工具 search_kb/read_page 自己接，旧工具原样转给 v2 手术刀）
分诊、预算、门牌、称重、落盘、恢复——全部原样继承。
这就是"Agent=可生长系统"的实证：加能力=加工具+更说明书，循环不动。

运行（★顺序体验 Agentic RAG）：
  python -X utf8 agent.py "算一下 3 + 5 * 2"          # 第一世
  python -X utf8 agent.py --resume "算一下 护栏"       # 第二世（失败页进档案）
  python -X utf8 agent.py --resume "查旧账：护栏那次拒绝的处方原文"
      ↑ 第三世：当前窗口里没有任何旧页——模型只能"自己决定检索"，
        实测走 search_kb → read_page 两拍，这就是 Agentic 检索的最小标本
  零命中演示： ... "查旧账：火星基地编号"（换词再试一次→如实收工）
"""

import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
sys.path.insert(1, os.path.join(_HERE, "..", "v3"))
sys.path.insert(2, os.path.join(_HERE, "..", "v2"))

import llm        # noqa: E402  v4 本地 Mock（会走三步舞的那个）
import memory     # noqa: E402  v3 器官
import triage     # noqa: E402  v2 分诊台
import kb         # noqa: E402  v4 新
from tools4 import run4            # noqa: E402  v4 新插座
from protocol4 import SYSTEM_V4, parse_reply  # noqa: E402

MAX_STEPS = 8
BUDGET_CHARS = int(os.environ.get("MEMORY_CHARS", "1800"))
SESS_PATH = os.path.join(_HERE, "sessions", "current.jsonl")


def record(history, sess, msg):
    history.append(msg)
    if sess:
        sess.write(msg)


def run_agent(user_input, history, sess):
    book = triage.Book()
    record(history, sess, {"role": "user", "content": user_input})

    for step in range(1, MAX_STEPS + 1):
        view, dropped = memory.sent_view(history, BUDGET_CHARS)
        tag = "（摘要归档了 %d 旧页）" % dropped if dropped else ""
        print("  [第 %d 圈] 记录账 %d 页 → 发送 %d 页%s｜体积≈%d字"
              % (step, len(history), len(view), tag, memory.estimate(view)))
        text = llm.chat_plain(view)
        record(history, sess, {"role": "assistant", "content": text})

        verdict = parse_reply(text)
        kind = verdict[0]

        if kind == "final":
            print("         [裁决] Final Answer，收工（处方 %d 张）" % book.total)
            return verdict[1]

        if kind == "format_error":
            act, remedy = triage.prescribe(triage.FORMAT_DRIFT, book, verdict[1], True)
            print("         [闸1拦] 纸面错 → 处方[%s]" % act)
            record(history, sess, {"role": "user", "content": memory.note("处方", remedy)})
            continue

        name, args = verdict[1], verdict[2]
        print("         [过闸1] Action：%s(%s)" % (name, args))
        ok, out, exc, idempotent = run4(name, args)      # ← 本版唯一的插座升级
        record(history, sess, {"role": "user",
                               "content": memory.note("观察", out if ok else "ERROR: " + out)})
        if ok:
            continue
        cls = triage.classify_runtime(exc, out)
        act, remedy = triage.prescribe(cls, book, out, idempotent)
        print("         [闸2诊] %s → 处方[%s]（幂等=%s）" % (cls, act, idempotent))
        record(history, sess, {"role": "user", "content": memory.note("处方", remedy)})

    return "已达到最大循环步数 %d，强制停止（硬保险丝）。" % MAX_STEPS


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = [a for a in sys.argv[1:]]
    resume = "--resume" in args
    forget = "--forget" in args
    ask = None
    for a in args:
        if not a.startswith("--"):
            ask = a
            break

    if forget and os.path.exists(SESS_PATH):
        os.remove(SESS_PATH)
        print("[记忆] 会话档案已清空：%s" % SESS_PATH)
        if not resume and ask is None:
            return

    sess = memory.SessionLog(SESS_PATH)
    skipped = 0
    if resume:
        history, skipped = memory.SessionLog.load(SESS_PATH)
        if not history:
            print("[恢复] 没有可恢复的档案，新开局。")
            history = [{"role": "system", "content": SYSTEM_V4}]
            sess.write(history[0])
        else:
            print("[恢复] 记录账找回 %d 页，跳过脏行 %d 行；档案库现有可检索页：%d"
                  % (len(history), skipped, len(kb.build_index())))
    else:
        if os.path.exists(SESS_PATH):
            bak = SESS_PATH.replace(".jsonl", "-" + time.strftime("%Y%m%d-%H%M%S") + ".jsonl")
            os.rename(SESS_PATH, bak)
            print("[记忆] 旧会话档案已归档：%s" % os.path.basename(bak))
        history = [{"role": "system", "content": SYSTEM_V4}]
        sess.write(history[0])

    if ask:
        print("你> %s" % ask)
        print("Agent> %s" % run_agent(ask, history, sess))
        _report(history, skipped)
        return

    print("Agent v4（Agentic 检索；查旧账说：查旧账：<关键词>；exit 看两账）")
    while True:
        try:
            user_input = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            _report(history, skipped)
            break
        if user_input.lower() == "reset":
            history = [{"role": "system", "content": SYSTEM_V4}]
            print("Agent> 内存账已清空；档案与检索库不受影响（长期记忆≠当前会话）。")
            continue
        print("Agent> %s" % run_agent(user_input, history, sess))


def _report(history, skipped=0):
    file_lines = 0
    if os.path.exists(SESS_PATH):
        with open(SESS_PATH, encoding="utf-8") as f:
            file_lines = sum(1 for _ in f)
    view, dropped = memory.sent_view(history, BUDGET_CHARS)
    ok = len(history) + skipped == file_lines
    print("\n──── 两账对照 ────")
    print("记录账：内存 %d 页 + 恢复跳行 %d = 档案 %d 行 %s"
          % (len(history), skipped, file_lines,
             "✓对上" if ok else "✗对不上！查 record() 旁路"))
    print("发送账：%d 页；裁则归档 %d 页→摘要 1 页｜体积 记录≈%d vs 发送≈%d（预算 %d）"
          % (len(view), dropped, memory.estimate(history), memory.estimate(view), BUDGET_CHARS))
    print("检索库：档案目录 %d 个文件，共 %d 页可查（长期记忆本体）"
          % (len([1 for f in os.listdir(kb.KB_DIR) if f.endswith(".jsonl")]),
             len(kb.build_index())))
    for i, m in enumerate(view):
        t = (m.get("content") or "").replace("\n", " ⏎ ")
        k = memory.note_kind(m)
        tag = "〔插话·%s〕" % k if k else ""
        if k:
            t = t.split("〕", 1)[-1]
        print("%02d [%-9s]%s %s" % (i, m["role"], tag, t[:80]))


if __name__ == "__main__":
    main()
