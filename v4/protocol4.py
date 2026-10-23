# -*- coding: utf-8 -*-
"""
protocol4.py —— 契约第四次扩员（双份契约现场：一次加两个住处）

新工具 search_kb / read_page 要同时登记：
  执法侧：TOOL_IMPLS 成员检查 + TOOL_ARGS 参数表（parse_reply 用）
  模型侧：SYSTEM 说明书加两行用法（模型读）
v2 预言过的"双份维护成本"，这是第四次现场缴纳。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "v3"))
import protocol3 as p3            # noqa: E402  链式把 v2/v1/v0 路径都拉通
import react_protocol as rp       # noqa: E402  v1 的执法表本体（已在 sys.modules）

rp.TOOL_IMPLS = dict(rp.TOOL_IMPLS)
rp.TOOL_IMPLS.update({"search_kb": True, "read_page": True})
rp.TOOL_ARGS = dict(rp.TOOL_ARGS)
rp.TOOL_ARGS.update({"search_kb": ["query"], "read_page": ["id"]})

SYSTEM_V4 = p3.SYSTEM_V3 + (
    "\n本次会话另可用（查旧档案=长期记忆）：\n"
    "- search_kb[input: 关键词]，在历史会话档案中检索，返回最多 3 条命中"
    "（格式：页号 [角色] 相似度 片段）；0 命中时换关键词再试一次，仍无则如实告知\n"
    "- read_page[input: 页号]，按命中里的页号取该页原文（页号形如 "
    "current-2026xx.jsonl#L12，必须来自 search_kb 的返回，不要自编）\n"
    "标准打法：先 search_kb 缩小范围，确需细节再 read_page——两拍完成一次查证。\n"
)

parse_reply = p3.parse_reply
