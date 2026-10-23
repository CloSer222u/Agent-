# -*- coding: utf-8 -*-
"""
tools.py —— Agent 的「手脚」

【本文件要教会你的三件事】
1. 工具 = 一个普通 Python 函数 + 一段 JSON Schema 说明书。
   函数负责「做」，Schema 负责「告诉模型你能做什么、怎么调用」。
2. Schema 会原样塞进发给大模型的请求里（payload 的 "tools" 字段），
   模型是通过「读说明书」来决定调哪个工具、传什么参数的——
   它自己并不会执行任何东西，执行永远发生在我们这一侧。
3. 工具返回的内容最终也会变成一条消息塞回对话里（role="tool"），
   供模型下一步阅读。也就是说：工具的输出会「累加」进上下文。

OpenAI 兼容的 function/tool schema 格式，和 DashScope、DeepSeek、
vLLM 等的格式是同一套，学会这个套路可以迁移到几乎所有模型服务。
"""

import ast
import datetime
import os

# 笔记类工具只允许写进这个目录，防止模型给一个 "C:/Windows/..." 就真去写
NOTES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notes")


# ──────────────────────────────────────────────
# 工具 1：计算器
# ──────────────────────────────────────────────
def calculator(expression):
    """安全地计算一个算术表达式，例如 "3 + 5 * 2"。

    为什么不用 eval()？因为 eval 能执行任意 Python。
    这里用 ast 白名单：只允许 数字 / 加减乘除幂取余 / 括号 / 一元负号，
    其余一律拒绝。这就是「给模型的能力要加护栏」的第一课。
    """
    node = ast.parse(expression, mode="eval")  # 先解析成语法树，不执行

    bin_ops = {
        ast.Add: operator_add, ast.Sub: operator_sub,
        ast.Mult: operator_mul, ast.Div: operator_div,
        ast.FloorDiv: operator_floordiv, ast.Mod: operator_mod,
        ast.Pow: operator_pow,
    }
    un_ops = {ast.UAdd: lambda x: +x, ast.USub: lambda x: -x}

    def _safe_eval(n):
        if isinstance(n, ast.Expression):
            return _safe_eval(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in bin_ops:
            return bin_ops[type(n.op)](_safe_eval(n.left), _safe_eval(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in un_ops:
            return un_ops[type(n.op)](_safe_eval(n.operand))
        raise ValueError("表达式里含有不允许的结构：%s" % type(n).__name__)

    result = _safe_eval(node)
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return str(result)


# 小工具函数（避免依赖第三方库，也顺便说明 operator 模块的用法）
def operator_add(a, b): return a + b
def operator_sub(a, b): return a - b
def operator_mul(a, b): return a * b
def operator_div(a, b): return a / b
def operator_floordiv(a, b): return a // b
def operator_mod(a, b): return a % b
def operator_pow(a, b):
    if abs(b) > 32:  # 防止模型写出 9**9**9 把机器算死——第二课：资源护栏
        raise ValueError("指数过大，拒绝执行")
    return a ** b


# ──────────────────────────────────────────────
# 工具 2：看时间
# ──────────────────────────────────────────────
def get_time():
    """返回当前日期时间（模型自己不知道现在几点，所以需要外部工具）。"""
    now = datetime.datetime.now()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return "%s，%s" % (now.strftime("%Y-%m-%d %H:%M:%S"), weekdays[now.weekday()])


# ──────────────────────────────────────────────
# 工具 3：写笔记（最简单的「持久化」工具）
# ──────────────────────────────────────────────
def write_note(filename, content):
    """把 content 写进 notes/filename，返回保存结果的文字描述。"""
    # 只取 basename：就算模型传 "..\\..\\evil.txt" 也只能落在 notes/ 里
    safe_name = os.path.basename(filename)
    if not safe_name:
        raise ValueError("文件名不能为空")
    os.makedirs(NOTES_DIR, exist_ok=True)
    path = os.path.join(NOTES_DIR, safe_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return "已写入 %s（%d 个字符）" % (path, len(content))


# ──────────────────────────────────────────────
# 说明书：告诉模型每个工具长什么样
# 这是「模型 ↔ 代码」之间的接口契约，逐字段看懂它
# ──────────────────────────────────────────────
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "calculator",                       # 名字要和函数名对上
            "description": "计算一个算术表达式并返回结果。支持 + - * / // % ** 和括号。",
            "parameters": {                             # JSON Schema 描述的入参
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "要计算的表达式，例如 \"3 + 5 * 2\"",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "获取当前的日期、时间和星期。无需任何参数。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_note",
            "description": "把一段文本保存为 notes 目录下的一条笔记文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "笔记文件名，例如 \"todo.txt\""},
                    "content": {"type": "string", "description": "要保存的正文内容"},
                },
                "required": ["filename", "content"],
            },
        },
    },
]

# 名字 → 实现。dispatch 靠这张表把「模型点的名」翻译成「真正执行的函数」
TOOL_IMPLS = {
    "calculator": calculator,
    "get_time": get_time,
    "write_note": write_note,
}


def dispatch(name, arguments):
    """执行一次工具调用，永远返回字符串（返回给模型的观察结果）。

    注意 try/except：工具炸了不能把整个 Agent 炸掉，
    而是把错误信息「原样喂回」给模型——模型看到报错会尝试自我修正，
    这就是最原始的「反思」，v2 阶段会围绕它做强化。
    """
    import json
    if isinstance(arguments, str):                      # 真实 API 传回的是 JSON 字符串
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return "ERROR: 工具参数不是合法 JSON：%r" % arguments[:200]
    fn = TOOL_IMPLS.get(name)
    if fn is None:
        return "ERROR: 不存在名为 %s 的工具" % name
    try:
        result = fn(**arguments)
        print("         [工具返回] %s -> %s" % (name, result))
        return str(result)
    except Exception as e:
        msg = "ERROR: %s(%s) 执行失败: %s: %s" % (name, arguments, type(e).__name__, e)
        print("         [工具报错] %s" % msg)
        return msg
