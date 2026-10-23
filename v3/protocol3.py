# -*- coding: utf-8 -*-
"""
protocol3.py —— v3 的契约追加页（双份契约的第三次同步）

v2 教过：说明书有两份住处。v3 加了"插话命名空间"这条新协议，
所以模型侧说明书（SYSTEM）要同步；执法侧这次**不需要**动——
因为 parse_reply 只管模型吐的 Action/Final，插话是我们自己写的，
不存在"模型违反插话格式"的裁决问题。双份契约也分"两份都要改"
和"只有一份归模型管"两种情形，这本身就是一课。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "v2"))
import protocol2 as p2  # noqa: E402  v2 已把 v1/v0 的路径链拉好

SYSTEM_V3 = p2.SYSTEM_V2.replace(
    "之后我会以 Observation: 开头的消息",          # v1 的旧话术——说明书过期处
    "之后我会以〔插话·观察〕开头的消息",           # v3 的门牌话术，改到与实物一致
) + (
    "\n插话约定（重要）：本对话中所有以〔插话·xx〕开头的 user 消息，"
    "都是系统代记而非真人发言——〔插话·观察〕是工具的真实结果；"
    "〔插话·处方〕是修复指令，你须按其行动；〔插话·摘要〕是旧对话被"
    "上下文预算归档后的案卷封面，你此前说做过的事以它为准继续，"
    "不要尝试重做已完成的操作。\n"
)

parse_reply = p2.parse_reply   # 裁决器依旧原样复用：闸1 三版未改一字
