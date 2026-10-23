# Agent From Scratch —— 从零构建 Agent 的渐进式原型

English: Five iterative prototypes of an LLM agent, built with **zero third-party dependencies** (Python stdlib only), each version adding exactly one architectural concept.

一个纯标准库实现的迷你 Agent 演进仓库。每一版只引入一个核心概念，后一版直接复用（而非重写）前一代组件——五版之后可以看清一个生产 Agent 框架里各部件的来龙去脉。

## 版本演进

| 版本 | 叠加的唯一概念 | 核心组件 |
|---|---|---|
| v0 | 最小闭环：function-calling 工具循环 | `agent.py` 循环 · `llm.py`（OpenAI 兼容调用 + 离线 Mock）· `tools.py`（工具 + Schema + 护栏） |
| v1 | 自研 ReAct 文本协议 | `react_protocol.py`：说明书进 system、正则三分裁决、格式漂移纠正回喂 |
| v2 | 错误处理与自我修复 | `triage.py`：故障分诊（纸面/参数/护栏/环境/未知 × 重试/绕道/收工）、分级重试预算、`runner2.py` 幂等闸门 |
| v3 | 会话记忆管理 | `memory.py`：JSONL 落盘与脏数据恢复、上下文预算滑窗、有损摘要、系统插话命名空间 |
| v4 | Agentic 检索（RAG 作为工具） | `kb.py`：分块→bigram 向量→余弦 TopK→回声过滤→低分阈值；`tools4.py`：`search_kb`/`read_page` 两拍定式、工具返回页宽闸 |

复用关系：v1–v4 直接 import v0 的工具层与护栏；v2–v4 复用 v1 的裁决器；v3–v4 复用 v2 的分诊台——**循环骨架五版未重写一行**。

## 快速开始

要求：Python 3.8+，无需安装任何第三方包；**没有 API Key 也能运行**（内置 Mock LLM 可完整演示循环机制）。

```bash
cd v0
python -X utf8 agent.py "帮我算一下 3 + 5 * 2"     # 离线 Mock
python -X utf8 agent.py                            # 多轮交互（exit 打印完整消息账本）

# 接入任意 OpenAI 兼容服务（默认 DashScope 兼容端点 / qwen-plus）
export DASHSCOPE_API_KEY=sk-xxx        # Windows PowerShell: $env:DASHSCOPE_API_KEY="sk-xxx"
# 可选项：AGENT_BASE_URL、AGENT_MODEL

# v2 起支持故障演示：
#   V1_MOCK_CHAOS=1     格式漂移 → 看分级处方
#   V2_MOCK_STUBBORN=1  屡教不改 → 看预算用尽后优雅收工
# v3/v4 支持跨进程恢复：
#   python agent.py --resume "接着算 6 * 7"      # 从会话档案找回记忆
#   MEMORY_CHARS=500 python agent.py "..."       # 调小上下文预算，观察滑窗+摘要
# v4 三世检索演示（见 v4 目录注释）：
#   python agent.py "算一下 3 + 5 * 2"
#   python agent.py --resume "算一下 护栏"
#   python agent.py --resume "查旧账：护栏那次拒绝的处方原文"
```

## 设计要点（代码里可直接指认）

- **协议**：模型无状态、上下文每圈全量重发；系统插话（观察/处方/摘要）统一命名空间，甄别单谓词
- **护栏**：表达式 AST 白名单（拒 eval）、文件操作路径收敛、指数上限、步数保险丝、页号越狱拦截
- **容错**：五类故障分级处方 + 按类重试预算 + 全局止损预算；非幂等工具遇结果不确定时禁止自动重试
- **记忆**：记录账（全量 JSONL，只追加）≠ 发送账（预算内滑窗 + 有损摘要）；恢复逐行校验、坏行可跳过
- **检索**：向量化器可替换位（`featurize()` 一处）、TopK/低分地板/回声过滤等质量闸全部显式参数化
- **可观测**：每圈打印账本页数/体积/处方计数；退出时打印两账对照与消息全簿

> 学习/研究用途的原型，非生产系统：体积计量用字符近似 token、检索用 n-gram 近似嵌入模型——
> 均为接口可替换的设计位，代码注释中已标明。
