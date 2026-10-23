# -*- coding: utf-8 -*-
"""
triage.py —— v2 的灵魂：错误分级表 + 处方笺 + 重试预算

v1 的世界只有两种结局（能裁决/不能裁决），v2 把"失败"拆成五种病，
每种病三要素：**能不能重试、重试几次、用什么话告诉模型**。

    ┌─ 纸面·格式漂移 ── 工具没碰过 → 重试绝对安全 → 给模板改写
    ├─ 现场·参数病   ── 工具跑了没副作用 → 可改参重试（幂等确认！）
    ├─ 现场·护栏拒绝 ── 同样参数必然再被拒 → 禁重试，换招或如实收工
    ├─ 现场·环境故障 ── 超时/磁盘：结果不确定 → 幂等工具可重试一次；
    │                                        非幂等工具禁止自动重试
    └─ 未知          ── 保守起见按一次重试处理，再犯即收工

v1 的预测里押了"按严重程度分级"——注意 v2 实际的分级轴是
「类型 × 可恢复性 × 幂等性」，不是严重度：护栏拒绝很"严重"但不该重试，
参数病很"轻"反而是唯一该马上重试的。严重度排序在这里会开错药。

本文件只回答"什么病开什么药"，不执行任何东西——分诊台和手术室分离。
"""

FORMAT_DRIFT = "纸面·格式漂移"
INPUT_BAD    = "现场·参数病"
TOOL_DENY    = "现场·护栏拒绝"
ENV_FAIL     = "现场·环境故障"
UNKNOWN      = "未知"

# 每种病的重试预算（次数是写进账本给模型看的，不是藏在我们内存里）
BUDGET = {FORMAT_DRIFT: 2, INPUT_BAD: 2, TOOL_DENY: 0, ENV_FAIL: 1, UNKNOWN: 1}
TOTAL_REPAIRS = 3  # 本轮提问最多吃几张处方——软预算，防止"每种病都还有余量"地打游击

REMEDY_FMT = (
    "【处方·%s 第%d/%d次】错误原因：%s。工具尚未执行，改写完全安全。"
    "请保持原意，仅改成规定格式重写一条 Action。"
)
REMEDY_INPUT = (
    "【处方·%s 第%d/%d次】工具执行失败：%s。该工具无副作用（幂等），"
    "请修正参数后重试一次，不要重复已成功的步骤。"
)
REMEDY_DENY = (
    "【处方·%s 预算0】该调用被安全护栏拒绝：%s。同样的参数重试必然再被拒。"
    "请换一种做法，或直接 Final Answer 向用户解释被拒原因。"
)
REMEDY_ENV_RETRY = (
    "【处方·%s 第%d/%d次】环境故障：%s。该工具幂等，重试安全，可再试一次。"
)
REMEDY_ENV_UNKNOWN = (
    "【处方·%s 预算0】环境故障且工具非幂等（可能已部分生效）：%s。"
    "禁止自动重试以免重复副作用。请 Final Answer 如实告知用户状态不确定。"
)
REMEDY_WRAP = (
    "【处方·预算用尽】多次修复未果（或预算已尽）。请停止调用工具，"
    "直接 Final Answer 向用户说明失败经过与原因——这是收工指令，不是错误。"
)


class Book(object):
    """处方记账本：每类病吃了多少张 + 总张数。账本可回放全靠这类明细。"""
    def __init__(self):
        self.per = {}
        self.total = 0

    def charge(self, cls):
        """记一次账，返回这是该类病的第几张处方（从 1 数）。"""
        self.per[cls] = self.per.get(cls, 0) + 1
        self.total += 1
        return self.per[cls]

    def over_total(self):
        return self.total > TOTAL_REPAIRS


def classify_runtime(exc, msg):
    """给「现场错」分诊：看异常类型 + 报错文本里的护栏关键词。

    ⚠ 工程上的正解是让工具抛**自定义异常类**（如 GuardrailViolation），
    而不是像现在这样嗅探字符串——这里为了代码量小用了嗅探
    （一笔显式记在注释里的技术债：工具一多必须换成类型分诊）。
    """
    if "拒绝" in msg or "护栏" in msg:
        return TOOL_DENY
    if isinstance(exc, (TimeoutError, OSError)):
        return ENV_FAIL
    if isinstance(exc, (SyntaxError, ValueError, TypeError, ZeroDivisionError)):
        return INPUT_BAD
    return UNKNOWN


def prescribe(cls, book, detail, idempotent):
    """裁决器/执行器把错误报到这里，返回二元组：(动作, 处方文本)。

    动作 ∈ {"retry", "reroute", "wrap"}——循环只负责执行动作，
    不再自己判断病情：判断住在分诊台，策略住在处方笺，执行住在循环。
    """
    if book.over_total():
        return ("wrap", REMEDY_WRAP)

    if cls == FORMAT_DRIFT:
        n = book.charge(cls)
        if n <= BUDGET[cls]:
            return ("retry", REMEDY_FMT % (cls, n, BUDGET[cls], detail))
        return ("wrap", REMEDY_WRAP)

    if cls == INPUT_BAD:
        n = book.charge(cls)
        if n <= BUDGET[cls]:
            return ("retry", REMEDY_INPUT % (cls, n, BUDGET[cls], detail))
        return ("wrap", REMEDY_WRAP)

    if cls == TOOL_DENY:
        book.charge(cls)
        return ("reroute", REMEDY_DENY % (cls, detail))

    if cls == ENV_FAIL:
        if not idempotent:
            book.charge(cls)
            return ("reroute", REMEDY_ENV_UNKNOWN % (cls, detail))
        n = book.charge(cls)
        if n <= BUDGET[cls]:
            return ("retry", REMEDY_ENV_RETRY % (cls, n, BUDGET[cls], detail))
        return ("wrap", REMEDY_WRAP)

    # UNKNOWN：只给一次机会
    n = book.charge(cls)
    if n <= BUDGET[cls]:
        return ("retry", REMEDY_INPUT % (UNKNOWN, n, BUDGET[cls], detail))
    return ("wrap", REMEDY_WRAP)
