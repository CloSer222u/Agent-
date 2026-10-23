# -*- coding: utf-8 -*-
"""
protocol2.py —— 给 v1 的契约"追加页"，不复制粘贴（也不放任漂移）

演示工程课：工具集扩大时，契约的**两个住处**都要同步更新——
说明书（SYSTEM 文字）和执法表（TOOL_ARGS / TOOL_IMPLS 成员检查）。
v1 时代"说明书两处居住"的维护成本，这里就是现场：看下面两处成对的动作。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "v1"))
import react_protocol as base  # noqa: E402  v1 的解析器与契约（不改它本体）

# 执法表扩员（拷贝后扩展，不污染 v0/v1 的全局）
base.TOOL_IMPLS = dict(base.TOOL_IMPLS)
base.TOOL_IMPLS["stamp_clock"] = True            # parse_reply 只做成员检查
base.TOOL_ARGS = dict(base.TOOL_ARGS)
base.TOOL_ARGS["stamp_clock"] = ["target"]

# 说明书同步加页——两行必须成对出现，这就是"双份契约"的日常成本
SYSTEM_V2 = base.SYSTEM_REACT + (
    "\n本次会话额外可用：\n"
    "- stamp_clock[input: 打卡对象]，打一次卡（真实追加写入，非幂等：\n"
    "  若它超时/报错，结果不确定，**不要重试同一次打卡**，听处方处置）\n"
)

parse_reply = base.parse_reply  # 裁决器本体不动用：v1 的它就是够用的
