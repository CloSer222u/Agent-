# -*- coding: utf-8 -*-
"""
runner2.py —— v2 的执行侧：把 dispatch 升级成「带回执的执行」

v1 的 dispatch 失败时把异常揉成一条 "ERROR: ..." 字符串回喂——
错误类型（是护栏拒、还是除零、还是超时）在那个字符串里**丢了**。
v2 需要类型信息才能分诊，所以这里重做一个 dispatch_structured：
返回结构 (ok, text, exc)：
   ok=True   text=结果
   ok=False  text=给人看的一行错误；exc=原始异常对象（交给 triage 分诊）

多带一个示范工具 stamp_clock（打卡）：它是**非幂等**的（每调用一次就
真的"打"一次），而且第一次调用故意模拟网络超时 → 用来演示
"现场·环境故障 + 非幂等 = 禁止自动重试"这条最凶险的组合。
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "v0"))
from tools import calculator, get_time, write_note  # noqa: E402  复用 v0 的三个纯实现

# name -> (实现函数, 是否幂等)
#   幂等 = 重复执行同样调用的效果 = 执行一次（可安全重试）
TOOL_META = {
    "calculator":   (calculator,   True),
    "get_time":     (get_time,     True),
    "write_note":   (write_note,   True),   # 同样内容覆盖写，算幂等
    "stamp_clock":  (None,         False),  # 下面定义，非幂等
}

_clock_state = {"failed_once": False}  # 演示用：让第一次调用超时


def stamp_clock(target):
    """打一次卡（真实副作用：往打卡簿追一行）。首次调用模拟网络超时。

    ⚠ v2.1 修正：副作用**先发生、后报错**——这才是"超时=结果未知"的真实
    长相（卡已打上，只是回执丢了）。原版在写入前抛错：副作用其实没发生，
    却宣称"可能已发生"——演示脚本撒谎，重复副作用就永远演示不出来。
    """
    log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clock.log")
    line = "%s 打卡 %s\n" % (datetime.datetime.now().strftime("%H:%M:%S"), target)
    with open(log, "a", encoding="utf-8") as f:   # "a"=追加，非幂等的物理来源
        f.write(line)
    if not _clock_state["failed_once"]:
        _clock_state["failed_once"] = True
        raise TimeoutError("打卡服务网络超时（回执丢失；卡是否打上：不确定）")
    return "打卡成功：%s" % target


TOOL_META["stamp_clock"] = (stamp_clock, False)


def run(name, arguments):
    """执行一次工具，返回 (ok, text, exc, idempotent)。"""
    if isinstance(arguments, str):
        import json
        try:
            arguments = json.loads(arguments or "{}")
        except ValueError:
            return (False, "工具参数不是合法 JSON", None, True)
    meta = TOOL_META.get(name)
    if meta is None:
        # 工具名幻觉：这不该由执行侧管，交给解析侧（v1 已拦）。兜底防御。
        return (False, "不存在名为 %s 的工具" % name, None, True)
    fn, idempotent = meta
    try:
        return (True, str(fn(**arguments)), None, idempotent)
    except Exception as e:            # noqa: BLE001 分诊台要看原始异常，不能在这揉成串
        return (False, "%s(%s) 执行失败：%s: %s" % (name, arguments, type(e).__name__, e),
                e, idempotent)
