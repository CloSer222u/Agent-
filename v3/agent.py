# -*- coding: utf-8 -*-
"""
agent.py（v3 版）—— 循环长出"记忆层"：记账走落盘，寄账走瘦身

v2→v3 的 diff 只有三类，循环逻辑（分诊/处方/预算）一字未动：
  ① 所有 history.append 换装 record()：记账的同时写进 sessions/current.jsonl
  ② 所有插话（观察/处方）换装 memory.note()：命名空间统一
  ③ 每圈发信前先过 sent_view()：发的是"发送账"，记的是"记录账"

运行：
  python -X utf8 agent.py "现在几点"          单句（自动落盘）
  python -X utf8 agent.py                     交互（exit 看记录账 vs 发送账）
  python -X utf8 agent.py --resume "接着算 6*7"   ★ 关进程后恢复记忆再问
  python -X utf8 agent.py --forget            清空会话文件（新档案）
  $env:MEMORY_CHARS=500 可把预算调小，逼出摘要归档看效果
"""

import os
import sys
import time

# 路径顺序是故意的：脚本目录第一（v3 的 llm/memory 优先命中），v2 第二（借分诊台与手术刀）。
# 若把 v2 插在最前，import llm 会抢走 v2/llm.py——跨目录复用的经典暗坑，已踩过记此。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
sys.path.insert(1, os.path.join(_HERE, "..", "v2"))
import llm        # noqa: E402  v3 本地（会认命名空间的那个）
import memory     # noqa: E402  v3 新器官
import runner2    # noqa: E402  v2 的手术刀（原样复用）
import triage     # noqa: E402  v2 的分诊台（原样复用）
from protocol3 import SYSTEM_V3, parse_reply  # noqa: E402

MAX_STEPS = 8
BUDGET_CHARS = int(os.environ.get("MEMORY_CHARS", "1800"))
SESS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions", "current.jsonl")


def record(history, sess, msg):
    """v3 的统一记账动作：账本一页，文件一行——原子化，永不"只记其一"。"""
    history.append(msg)
    if sess:
        sess.write(msg)


def run_agent(user_input, history, sess):
    book = triage.Book()
    record(history, sess, {"role": "user", "content": user_input})

    for step in range(1, MAX_STEPS + 1):
        view, dropped = memory.sent_view(history, BUDGET_CHARS)   # ← 发送账变形
        tag = "（摘要归档了 %d 旧页）" % dropped if dropped else "（未瘦身）"
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
        ok, out, exc, idempotent = runner2.run(name, args)
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
            history = [{"role": "system", "content": SYSTEM_V3}]
            sess.write(history[0])
        else:
            print("[恢复] 记录账找回 %d 页，跳过脏行 %d 行"
                  % (len(history), skipped))
    else:
        # 新开局：旧档案改名归档（会话管理的真实做法——而不是覆盖或删除）
        if os.path.exists(SESS_PATH):
            bak = SESS_PATH.replace(".jsonl", "-" + time.strftime("%Y%m%d-%H%M%S") + ".jsonl")
            os.rename(SESS_PATH, bak)
            print("[记忆] 旧会话档案已归档：%s" % os.path.basename(bak))
        history = [{"role": "system", "content": SYSTEM_V3}]
        sess.write(history[0])

    if ask:
        print("你> %s" % ask)
        print("Agent> %s" % run_agent(ask, history, sess))
        _report(history, skipped)
        return

    print("Agent v3（记忆管理；exit 看两账对照，reset 清内存不清档案）")
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
            history = [{"role": "system", "content": SYSTEM_V3}]
            print("Agent> 内存记忆已清空；注意：档案文件仍保留全部记录页（记录账≠内存账）。")
            continue
        print("Agent> %s" % run_agent(user_input, history, sess))


def _report(history, skipped=0):
    """两账对照的现场教学。

    对照公式：档案行 = 内存账页 + 恢复时跳过的脏行。
    （被跳的脏行仍留在档案里——档案只追加不回改，伤疤是永久记录；
     所以"找回页数 != 文件行数"未必是 bug，先把 skipped 算平再喊打。）
    """
    file_lines = 0
    if os.path.exists(SESS_PATH):
        with open(SESS_PATH, encoding="utf-8") as f:
            file_lines = sum(1 for _ in f)
    view, dropped = memory.sent_view(history, BUDGET_CHARS)
    ok = len(history) + skipped == file_lines
    print("\n──── 两账对照 ────")
    print("记录账：内存 %d 页 + 恢复跳行 %d = 档案 %d 行 %s"
          % (len(history), skipped, file_lines,
             "✓对上" if ok else "✗对不上！查 record() 是否有旁路 append，或 reset 后未计"))
    print("发送账（此刻寄出的视图）：%d 页；若裁则归档 %d 页→摘要 1 页" % (len(view), dropped))
    print("体积：记录≈%d 字 vs 发送≈%d 字（预算 %d）"
          % (memory.estimate(history), memory.estimate(view), BUDGET_CHARS))
    print("\n──── 发送账长相（模型下圈实际读到的）────")
    for i, m in enumerate(view):
        t = (m.get("content") or "").replace("\n", " ⏎ ")
        k = memory.note_kind(m)
        tag = "〔插话·%s〕" % k if k else ""
        if k:
            t = t.split("〕", 1)[-1]        # 标记只显示一次，正文去重
        print("%02d [%-9s]%s %s" % (i, m["role"], tag, t[:80]))


if __name__ == "__main__":
    main()
