# -*- coding: utf-8 -*-
"""
tools4.py —— v4 的两只新手，及"源层页宽闸"的首次落地

v3 讨论欠下的账：工具返回值不瘦身=账本单页通胀（MCP 8866 字旧案）。
本版两只新工具都读旧档案、**全部只读、幂等、返回定宽**——
工具设计第一次把"这页该多大、全文在哪、线索怎么留"当成显式决定。
"""

import kb

MAX_RETURN = 600   # 源层页宽闸：单次返回超过这个字数的，截断并留线索


def search_kb(query):
    """两级检索的第一级：缩小范围。返回最多 3 条命中（页号+片段），定宽。"""
    hits = kb.search(query)
    if not hits:
        return ("检索结果：0 命中。档案里没有相关内容——"
                "可换个关键词再查一次，或如实告诉用户查不到。")
    lines = ["检索结果：%d 命中（相似度降序）：" % len(hits)]
    for score, pid, role, txt in hits:
        lines.append("  %s [%s] %.3f %s" % (pid, role, score,
                                            txt.replace("\n", " ⏎ ")[:48]))
    return "\n".join(lines)[:MAX_RETURN]


def read_page(page_id):
    """两级检索的第二级：按页号取原文。超长也截，但头尾都留+省略计数。"""
    role, txt = kb.read(page_id)
    if len(txt) > MAX_RETURN:
        omitted = len(txt) - (MAX_RETURN - 100)
        return "[%s] %s …（中间已按页宽闸省略 %d 字）… %s" % (
            role, txt[:MAX_RETURN - 100], omitted, txt[-60:])
    return "[%s] %s" % (role, txt)


def run4(name, args):
    """统一执行入口：新工具自己接，旧工具转给 v2 手术刀。
    只读工具恒幂等（True），错误照样带异常对象去分诊。"""
    if name == "search_kb":
        try:
            return (True, search_kb(args.get("query", "")), None, True)
        except Exception as e:
            return (False, "%s: %s" % (type(e).__name__, e), e, True)
    if name == "read_page":
        try:
            return (True, read_page(args.get("id", "")), None, True)
        except Exception as e:
            return (False, "%s: %s" % (type(e).__name__, e), e, True)
    import runner2
    return runner2.run(name, args)
