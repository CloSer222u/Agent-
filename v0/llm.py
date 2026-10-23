# -*- coding: utf-8 -*-
"""
llm.py —— Agent 的「大脑接口」

对 agent.py 来说，大脑只需要暴露一个函数：

    chat(messages, tools) -> assistant_message

输入是「到目前为止的完整对话」（累加！），输出是模型下一步的动作：
  - 要么直接给一段文字（任务结束）
  - 要么给一个 tool_calls 列表（模型想调用工具，请你去执行）

本文件提供两种实现：
  1) RealLLM ：用 Python 标准库 urllib 直接 POST 到 OpenAI 兼容接口
     （默认用阿里云百炼 DashScope 的 compatible-mode）。
     不用 openai SDK 是故意的——让你看清 HTTP 层到底发了什么 JSON。
  2) MockLLM ：不联网，用几条 if 规则假装自己是模型。
     它的作用是让「Agent 循环」这个机制在没有任何 API Key 的情况下
     也能跑通、能调试。机制和智能是两回事，先搭机制。

【环境变量】
  DASHSCOPE_API_KEY  你的百炼 API Key（普通 sk- 或 sk-ws- 开头）。
                     没设置时自动退回 MockLLM。
                     ⚠ 不要用 sk-sp- 开头的订阅 token-plan key 跑这种脚本。
  AGENT_BASE_URL     可选，默认 https://dashscope.aliyuncs.com/compatible-mode/v1
  AGENT_MODEL        可选，默认 qwen-plus（支持 function calling 的便宜型号）
"""

import json
import os
import re
import urllib.error
import urllib.request

BASE_URL = os.environ.get("AGENT_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL = os.environ.get("AGENT_MODEL", "qwen-plus")
API_KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()


_mock_warned = False


def chat(messages, tools):
    """统一入口：有 Key 走真模型，没 Key 走 Mock。返回 assistant 消息字典。"""
    global _mock_warned
    if API_KEY:
        return _real_chat(messages, tools)
    if not _mock_warned:
        print("[llm] 未检测到环境变量 DASHSCOPE_API_KEY，本次进程使用 MockLLM（离线规则假模型）。")
        _mock_warned = True
    return _mock_chat(messages, tools)


# ══════════════════════════════════════════════
# 一、真实模型调用
# ══════════════════════════════════════════════
def _real_chat(messages, tools):
    payload = {
        "model": MODEL,
        "messages": messages,   # 注意：每次都把「全部历史」重发一遍。
                                # 模型是无状态的，它的「记忆」完全来自这个数组。
        "tools": tools,
        "tool_choice": "auto",  # auto = 模型自己决定要不要用工具
    }
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + API_KEY,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            "模型接口返回 HTTP %s：%s\n请检查 API Key / 模型名 / BaseURL 是否匹配。"
            % (e.code, e.read().decode("utf-8", "replace")[:400])
        )

    # 响应里 choices[0].message 就是我们要的 assistant 消息，
    # 它的形状保证是：{"content": 文字或None, "tool_calls": 列表或None}
    return body["choices"][0]["message"]


# ══════════════════════════════════════════════
# 二、Mock 模型（离线规则，模拟「聪明」的假象）
# ══════════════════════════════════════════════
# Mock 的判断逻辑故意写得非常笨，目的是让你对比出：
# 真模型「聪明」在哪——它聪明在能读懂工具说明书并自己组织参数，
# 而下面这些规则全是人肉写死的 if。
def _mock_chat(messages, tools):
    last_user = ""
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_user_idx = i
            last_user = messages[i]["content"]
            break

    # 规则 A：如果「本轮提问之后」已经出现了工具的执行结果（role=tool），
    #          说明「观察」已到位，Mock 直接结束任务（模仿模型的收尾动作）。
    # 为什么要限定「之后」？因为 history 是累加的，上一轮的 tool 结果还躺在
    # 历史里。真模型能分清「哪些结果还没用上」，Mock 只能人肉切窗口。
    tool_results = [m["content"] for m in messages[last_user_idx:] if m.get("role") == "tool"]
    if tool_results:
        joined = "；".join(tool_results)
        return {
            "role": "assistant",  # 真实 API 返回的消息一定带 role，Mock 必须模仿到位
            "content": "任务完成。工具查到的结果是：%s。（我是 Mock，只会复述；"
                       "配上真实 API Key 后，模型会把这些结果组织成自然语言回答。）" % joined
        }

    # 规则 B：识别「算一下 3+5*2」这类请求 → 发起 calculator 工具调用
    m = re.search(r"[-+*/%()\d\.\s]{3,}", last_user)
    if re.search(r"算|计算|\d.*[+\-*/].*\d", last_user) and m:
        return _fake_tool_call("calculator", {"expression": m.group(0).strip()})

    # 规则 C：识别记笔记请求 → 发起 write_note 工具调用
    #（注意它排在时间规则前面：写死的规则会互相抢匹配，
    #  调顺序、调正则都是调试 Mock 的日常——真模型则靠语义自己判断）
    if re.search(r"笔记|记下|保存|写到", last_user):
        m2 = re.search(r"[：:]\s*(.+)$", last_user)
        return _fake_tool_call("write_note", {
            "filename": "mock_note.txt",
            "content": m2.group(1) if m2 else last_user,
        })

    # 规则 D：识别时间类问题 → 发起 get_time 工具调用
    if re.search(r"几点|时间|日期|今天|星期", last_user):
        return _fake_tool_call("get_time", {})

    # 规则 E：都不匹配 → 直接回文本（等价于「不调工具，直接答」）
    return {"role": "assistant", "content": "（Mock 兜底回复）我收到了：%s。设了 DASHSCOPE_API_KEY 后"
            "就能用真模型好好回答你。" % last_user}


_call_seq = [0]  # 用于给每次工具调用编一个唯一 id


def _fake_tool_call(name, args):
    """构造一个和真实 API 形状一模一样的 tool_calls 消息。

    真实 API 的返回长这样（原样抄下来给你看结构）：
    {
      "content": null,
      "tool_calls": [
        {
          "id": "call_abc123",            <- 调用编号，回传结果时要对上
          "type": "function",
          "function": {
             "name": "calculator",
             "arguments": "{\\"expression\\": \\"3+5\\"}"   <- 参数是 JSON 字符串！
          }
        }
      ]
    }
    """
    _call_seq[0] += 1
    return {
        "role": "assistant",  # 同上：这条消息以后会原样回传给模型，字段缺一不可
        "content": None,
        "tool_calls": [
            {
                "id": "call_mock_%d" % _call_seq[0],
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ],
    }
