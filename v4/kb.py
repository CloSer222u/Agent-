# -*- coding: utf-8 -*-
"""
kb.py —— v4 的检索内核：档案 → 索引 → 相似度排序

真实 RAG 用模型嵌入（embedding）把文本变成向量；本版**零依赖**，
用"字符 2-gram 词频向量 + 余弦相似度"顶替——换掉的只是向量化器，
其余机制（分块→建向量→比距离→TopK）与真系统同构。
接口就一个函数 featurize()，哪天换真嵌入，只动它。

分块（chunk）在这里是免费的：JSONL 一页=一条记录，天然分块。
"""

import io
import json
import math
import os
import re
from collections import Counter

KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions")


def _norm(s):
    """只留汉字和字母数字，统一小写——标点/空格不进特征。"""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", (s or "").lower())


def featurize(text):
    """向量化器（本版的"迷你 embedding"）：字符 bigram 频数字典。"""
    n = _norm(text)
    if len(n) < 2:
        return Counter({n: 1}) if n else Counter()
    return Counter(n[i:i + 2] for i in range(len(n) - 1))


def _cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if (na and nb) else 0.0


def iter_pages():
    """遍历档案目录里所有会话文件，产出可检索页（跳过 system 法条页——
    它每世一份，检索它只会霸榜，不如不索引）。"""
    if not os.path.isdir(KB_DIR):
        return
    for fn in sorted(os.listdir(KB_DIR)):
        if not fn.endswith(".jsonl"):
            continue
        path = os.path.join(KB_DIR, fn)
        with io.open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    m = json.loads(line)
                except ValueError:
                    continue  # 恢复要假设脏（v3 铁律在检索侧继续生效）
                if not isinstance(m, dict) or m.get("role") == "system":
                    continue
                txt = m.get("content") or ""
                if txt:
                    yield "%s#L%d" % (fn, i), m.get("role", "?"), txt


def build_index():
    """每次查询现建（档案小，诚实第一：改过档案立刻检索得到，无缓存失效问题）。
    档案大了这行就该换成持久索引+增量——记下这笔债即可。"""
    return [(pid, role, txt, featurize(txt)) for pid, role, txt in iter_pages()]


def search(query, topk=3):
    """检索排序。一道专属闸：**自回声过滤**。
    刚问的问题已被记进档案，逐字包着查询本身——不排除的话，
    检索到的永远是"自己刚说的话"而非证据。
    判据用"包含"不用"高相似阈值"：实测回声页的余弦只有 0.877，
    阈值拦不住；但回声页必然原样含查询串（它是问题的复读），包含判据精准。
    真实系统同款病：查询回显历史霸榜 TopK，解法有 MMR 多样性重排/
    排除来源消息 id 等——这里用最便宜的精确版。"""
    qn = _norm(query)
    qv = featurize(query)
    scored = []
    for pid, role, txt, v in build_index():
        if qn and len(qn) >= 4 and qn in _norm(txt):
            continue                      # 回声页不配当证据
        s = _cosine(qv, v)
        if s >= 0.05:                     # 低分地板：0.03 的 bigram 巧合是噪音，
            scored.append((s, pid, role, txt))   # 真系统的 min-score 阈值同款
    scored.sort(key=lambda x: -x[0])
    return scored[:topk]


def read(page_id):
    """按页号取原文。页号=文件名#L行号，来自 search 的命中，非模型自由发挥——
    但仍按不可信输入处理：basename 防门牌越狱（v0 护栏思想原样在岗）。"""
    fn, _, ln = page_id.partition("#L")
    fn = os.path.basename(fn)
    if not fn.endswith(".jsonl"):
        raise ValueError("页号格式非法：%s" % page_id)
    try:
        target = int(ln)
    except ValueError:
        raise ValueError("页号行码非法：%s" % page_id)
    with io.open(os.path.join(KB_DIR, fn), encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i == target:
                m = json.loads(line)
                return m.get("role", "?"), m.get("content") or ""
    raise ValueError("页号不存在：%s" % page_id)
