"""
ConvIndexer — 生产级对话索引模块

从对话消息中提取结构化段(segment) + 段间关系(relation) + 全局摘要(global_summary) + 结论(conclusion)。
支持长对话自动分段、滚动处理（pending/complete 状态机）、全局回顾。

存储到三张独立表：
  conv_index      — 对话级（一行 = 一条对话）
  conv_segments   — 段级（一行 = 一个叙事段，summary 可做 embedding）
  conv_relations  — 段间关系（一行 = 一条关系）
"""
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
from core.json_parse import safe_json_parse


# ── 模型配置 ──────────────────────────────────────────

MODEL_PROFILES = {
    "35b-apex-v36": {
        "model_id": "qwen3-6-35b-apex-nothink",
        "label": "Qwen3.6-35B-Apex (nothink)",
        "desc": "17.3G +vision",
    },
    "35b-apex-v35": {
        "model_id": "qwen3-5-35b-apex-nothink",
        "label": "Qwen3.5-35B-Apex (nothink)",
        "desc": "17.3G +vision",
    },
    "35b-ud-v36": {
        "model_id": "qwen3-6-35b-ud-nothink",
        "label": "Qwen3.6-35B-UD (nothink)",
        "desc": "17.7G +vision",
    },
    "35b-ud-v35": {
        "model_id": "qwen3-5-35b-ud-nothink",
        "label": "Qwen3.5-35B-UD (nothink)",
        "desc": "17.5G nothink",
    },
    "27b": {
        "model_id": "qwen3-6-27b-iq4-nl",
        "label": "Qwen3.6-27B-IQ4_NL (think=False)",
        "desc": "~16G dense 27B",
    },
    "9b": {
        "model_id": "qwen3-5-9b-glm5-1-distill-v1-q8-0",
        "label": "Qwen3.5-9B-Distill (think=False)",
        "desc": "9.5G +vision",
    },
    # 云端模型（通过 Gateway 直连）
    "ds-v4-flash": {
        "model_override": "gateway:deepseek:deepseek-v4-flash",
        "label": "DeepSeek V4 Flash",
        "desc": "云端直连",
    },
    "ds-v4-pro": {
        "model_override": "gateway:deepseek:deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "desc": "云端直连",
    },
}

SEGMENT_MAX_CHARS = 12000
SEGMENT_OVERLAP = 2

SCHEMA_PATH = config.PROMPTS_DIR / "schemas" / "conv_unified_schema.json"


# ── 工具函数 ──────────────────────────────────────────

def _load_schema() -> dict:
    """加载 JSON Schema（启动时调用一次）"""
    if SCHEMA_PATH.exists():
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return {
        "type": "object",
        "properties": {
            "segments": {"type": "array", "items": {"type": "object"}},
            "relations": {"type": "array", "items": {"type": "object"}},
            "global_summary": {"type": ["string", "null"]},
            "conclusion": {"type": ["string", "null"]},
        },
        "required": ["segments", "relations"],
    }


def _load_messages(conn, conv_id: str) -> list[dict]:
    """从 DB 加载对话消息（排除 system 消息）"""
    rows = conn.execute("""
        SELECT sender, text, sequence
        FROM conversation_messages
        WHERE conversation_id = ? AND sender != 'system'
        ORDER BY sequence ASC
    """, (conv_id,)).fetchall()
    return [dict(r) for r in rows]


def _split_long_conversation(messages: list[dict],
                              max_chars: int = SEGMENT_MAX_CHARS,
                              overlap: int = SEGMENT_OVERLAP) -> list[list[dict]]:
    """将消息按字符数切割为物理段，带 overlap"""
    if not messages:
        return []
    total_chars = sum(len(m.get("text", "")) for m in messages)
    if total_chars <= max_chars:
        return [messages]

    segments = []
    start = 0
    while start < len(messages):
        end = start
        chars = 0
        while end < len(messages):
            msg_chars = len(messages[end].get("text", ""))
            if chars + msg_chars > max_chars and end > start:
                break
            chars += msg_chars
            end += 1
        segments.append(messages[start:end])
        if end >= len(messages):
            break
        next_start = end - overlap
        if next_start <= start:
            next_start = start + 1
        start = next_start

    # 尾部合并：最后一段太短则并入倒数第二段
    while len(segments) >= 2:
        last = segments[-1]
        prev = segments[-2]
        merged_chars = sum(len(m.get("text", "")) for m in prev + last)
        if len(last) <= 3 and merged_chars <= max_chars * 1.2:
            segments[-2] = prev + last
            segments.pop()
        else:
            break
    return segments


def _render_segment(messages: list[dict]) -> str:
    """渲染消息列表为带序号的文本"""
    lines = []
    for m in messages:
        sender = (m.get("sender") or "").lower()
        role = "\u7528\u6237" if sender in ("user", "human", "\u7528\u6237") else "AI"
        text = (m.get("text") or "").replace("\n", " ").strip()
        idx = m["_1based_idx"]
        lines.append(f"[{idx}] {role}\uff1a{text}")
    return "\n".join(lines)


def _build_user_prompt(segment_messages: list[dict], pending: Optional[dict],
                       completed: list[dict], existing_relations: list[dict] = None,
                       is_last_step: bool = False) -> str:
    """构建段处理模式的 user prompt（Mode A）
    XML标签包裹：前缀（摘要+关系，cache命中）+ 当前段原文（变量）
    """
    parts = []

    # 已完成段摘要 + 关系内联（前缀，追加式增长）
    # [] = 段摘要，<> = 关系。每段后面钉着它发出的关系，逐个追加不破坏前缀缓存。
    if completed:
        lines = []
        for i, c in enumerate(completed):
            span = c['msg_span']
            line = f"  [{i}] {span[0]}-{span[1]} {c['name']}：{c['summary']}"
            # 找到这个段发出的关系，内联到段后面
            if existing_relations:
                out_rels = [f"<{r['from']}→{r['to']}:{r['type']}>"
                           for r in existing_relations if r['from'] == i]
                if out_rels:
                    line += " " + " ".join(out_rels)
            lines.append(line)
        parts.append("<completed_segments>\n" + "\n".join(lines) + "\n</completed_segments>")

    # 当前段原文（变量，每次重新算）
    if pending:
        pend_text = _render_segment(pending["messages"])
        seg_text = _render_segment(segment_messages)
        parts.append("<pending>\n" + pend_text + "\n</pending>\n<current_segment>\n" + seg_text + "\n</current_segment>")
    else:
        seg_text = _render_segment(segment_messages)
        parts.append("<current_segment>\n" + seg_text + "\n</current_segment>")

    return "\n\n".join(parts)


def _build_review_prompt(completed: list[dict], existing_relations: list[dict]) -> str:
    """全局回顾模式的 user prompt（Mode B）
    XML标签包裹：前缀（摘要+关系内联）+ 回顾指令
    """
    parts = []

    # 摘要 + 关系内联
    lines = []
    for i, c in enumerate(completed):
        span = c['msg_span']
        line = f"  [{i}] {span[0]}-{span[1]} {c['name']}：{c['summary']}"
        if existing_relations:
            out_rels = [f"<{r['from']}→{r['to']}:{r['type']}>"
                       for r in existing_relations if r['from'] == i]
            if out_rels:
                line += " " + " ".join(out_rels)
        lines.append(line)
    parts.append("<completed_segments>\n" + "\n".join(lines) + "\n</completed_segments>")

    # 回顾指令
    parts.append("<instruction>请进行全局回顾：输出 global_summary、conclusion，并补充远距离跨段关系（距离≥3）。segments 输出空数组。</instruction>")

    return "\n\n".join(parts)


def _validate_step(parsed: dict, all_msg_indices: set, n_completed: int,
                   is_review_step: bool = False) -> list[str]:
    """验证模型输出的结构和语义合法性"""
    errs = []
    if not isinstance(parsed, dict):
        return ["顶层不是 dict"]

    for k in ("segments", "relations"):
        if k not in parsed:
            errs.append(f"缺字段 {k}")

    segs = parsed.get("segments") or []

    if not is_review_step:
        for i, seg in enumerate(segs):
            if not isinstance(seg, dict):
                continue
            span = seg.get("msg_span") or []
            if len(span) >= 2 and span[0] is not None and span[1] is not None:
                if span[0] > span[1]:
                    errs.append(f"segments[{i}] msg_span 反了: {span}")
                elif span[0] not in all_msg_indices and span[1] not in all_msg_indices:
                    errs.append(f"segments[{i}] msg_span {span} 超出输入范围")
            if "complete" not in seg:
                errs.append(f"segments[{i}] 缺 complete")
        for i, seg in enumerate(segs):
            if isinstance(seg, dict) and seg.get("complete") is False and i < len(segs) - 1:
                errs.append(f"segments[{i}] complete=false 但不是最后一个")
    else:
        if segs:
            errs.append(f"全局回顾步骤 segments 应为空数组，实际有 {len(segs)} 个")

    rels = parsed.get("relations") or []
    n_total = n_completed + (0 if is_review_step else len(segs))
    for i, r in enumerate(rels):
        if not isinstance(r, dict):
            continue
        fr = r.get("from")
        to = r.get("to")
        if isinstance(fr, int) and (fr < 0 or fr >= n_total):
            errs.append(f"relations[{i}] from={fr} \u8d8a\u754c (\u5171 {n_total} \u6bb5)")
        if isinstance(to, int) and (to < 0 or to >= n_total):
            errs.append(f"relations[{i}] to={to} \u8d8a\u754c (\u5171 {n_total} \u6bb5)")

    gs = parsed.get("global_summary")
    conc = parsed.get("conclusion")
    if not is_review_step:
        if gs is not None:
            errs.append("\u6bb5\u5904\u7406\u6b65\u9aa4\u4f46 global_summary \u4e0d\u4e3a null")
        if conc is not None:
            errs.append("\u6bb5\u5904\u7406\u6b65\u9aa4\u4f46 conclusion \u4e0d\u4e3a null")
    else:
        if gs is None:
            errs.append("\u5168\u5c40\u56de\u987e\u6b65\u9aa4\u4f46 global_summary \u4e3a null")

    return errs


# ── 输出质量检测 ──────────────────────────────────────

# 重复模式：同一个词连续出现3次以上
_REPEAT_RE = re.compile(r'([\u4e00-\u9fff]{2,})\1{2,}|([a-zA-Z]{3,})\2{2,}')

# 已知坍塌词
_GARBAGE_WORDS = {"kampf", "caste", "宗族", "ington", "strain"}

# 合法关系类型
_VALID_REL_TYPES = {
    # 核心6种（高频）
    "前提", "因果", "演进", "应用", "对比", "实例",
    # 扩展（特定场景）
    "包含", "衍生", "用途", "等价", "矛盾", "时序",
}


def _check_quality(parsed: dict, raw_text: str) -> list[str]:
    """检测模型输出是否被 token 坍塌污染。返回错误列表。"""
    errs = []

    # 1. 检测 raw text 中的重复循环（最可靠）
    repeats = _REPEAT_RE.findall(raw_text)
    if repeats:
        words = [m[0] or m[1] for m in repeats[:3]]
        errs.append(f"输出含重复循环: {', '.join(words)}")
        return errs  # 重复循环是最严重的，直接返回

    # 2. 检测段摘要质量
    for i, seg in enumerate(parsed.get("segments") or []):
        if not isinstance(seg, dict):
            continue
        summary = seg.get("summary", "") or ""
        name = seg.get("name", "") or ""

        # 摘要超长
        if len(summary) > 800:
            errs.append(f"segments[{i}] 摘要超长 ({len(summary)}字)")

        # 摘要含坍塌词
        sl = summary.lower()
        for gw in _GARBAGE_WORDS:
            if sl.count(gw) >= 2:
                errs.append(f"segments[{i}] 含坍塌词:{gw}({sl.count(gw)}次)")
        if sl.count("平台") + sl.count("platform") > 5:
            errs.append(f"segments[{i}] 平台词过多({sl.count('平台')+sl.count('platform')}次)")

        # name 异常（允许中文书名号《》、括号（）等常见标点）
        if re.search(r'[{}<>/\\]', name):
            errs.append(f"segments[{i}] name含异常字符: {name[:50]}")
        if len(name) > 60:
            errs.append(f"segments[{i}] name超长 ({len(name)}字)")

    # 3. 检测关系类型
    for i, r in enumerate(parsed.get("relations") or []):
        if isinstance(r, dict):
            rt = r.get("type", "")
            if rt and rt not in _VALID_REL_TYPES:
                errs.append(f"relations[{i}] 非法类型: {rt[:20]}")

    # 4. 检测全局摘要
    gs = parsed.get("global_summary") or ""
    if gs:
        gsl = gs.lower()
        for gw in _GARBAGE_WORDS:
            if gsl.count(gw) >= 2:
                errs.append(f"global_summary 含坍塌词:{gw}")
        if len(gs) > 2000 and gsl.count("平台") + gsl.count("platform") > 5:
            errs.append(f"global_summary 超长且含平台词")

    return errs


# ── ConvIndexer ──────────────────────────────────────

class ConvIndexer:
    """生产级对话索引器：滚动分段 + 全局回顾 + 增量存储"""

    def __init__(self, router, claims_manager, prompt_manager):
        self.router = router
        self.cm = claims_manager
        self.pm = prompt_manager
        self._schema = _load_schema()
        self._ensure_tables()

        # 批量进度追踪
        self._batch_done = 0
        self._batch_total = 0
        self._batch_start_time = 0.0

    def _ensure_tables(self):
        """确保 conv_index / conv_segments / conv_relations 三张表存在"""
        self.cm.conn.executescript("""
            CREATE TABLE IF NOT EXISTS conv_index (
                conv_id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                global_summary TEXT,
                conclusion TEXT,
                model_key TEXT NOT NULL DEFAULT '',
                model_id TEXT NOT NULL DEFAULT '',
                model_label TEXT NOT NULL DEFAULT '',
                msg_count INTEGER DEFAULT 0,
                total_chars INTEGER DEFAULT 0,
                n_physical_segments INTEGER DEFAULT 0,
                n_segments INTEGER DEFAULT 0,
                n_relations INTEGER DEFAULT 0,
                elapsed_total_s REAL DEFAULT 0,
                total_errors INTEGER DEFAULT 0,
                steps_json TEXT DEFAULT '[]',
                errors_json TEXT DEFAULT '[]',
                source TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conv_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conv_id TEXT NOT NULL,
                seg_idx INTEGER NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                msg_span_start INTEGER,
                msg_span_end INTEGER,
                summary TEXT NOT NULL DEFAULT '',
                complete INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (conv_id) REFERENCES conv_index(conv_id),
                UNIQUE(conv_id, seg_idx)
            );

            CREATE TABLE IF NOT EXISTS conv_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conv_id TEXT NOT NULL,
                from_idx INTEGER NOT NULL,
                to_idx INTEGER NOT NULL,
                rel_type TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'segment',
                FOREIGN KEY (conv_id) REFERENCES conv_index(conv_id)
            );

            CREATE INDEX IF NOT EXISTS idx_conv_segments_conv_id ON conv_segments(conv_id);
            CREATE INDEX IF NOT EXISTS idx_conv_relations_conv_id ON conv_relations(conv_id);
        """)

        # 增量添加 embedding + sparse 列（已存在则跳过）
        for table, col in [("conv_segments", "embedding"), ("conv_index", "embedding")]:
            try:
                self.cm.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} BLOB")
            except Exception:
                pass
        for table, col in [("conv_segments", "sparse_vector"), ("conv_index", "sparse_vector")]:
            try:
                self.cm.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
            except Exception:
                pass
        self.cm.conn.commit()

    # ── 存储接口 ─────────────────────────────────────

    def _save_result(self, conv_id: str, result: dict):
        """保存索引结果到三张表（事务）"""
        now = datetime.now().isoformat()
        segments = result.get("final_segments") or []
        relations = result.get("final_relations") or []

        try:
            self.cm.conn.execute("BEGIN")

            # 1. conv_index — 对话级
            self.cm.conn.execute(
                """INSERT OR REPLACE INTO conv_index
                    (conv_id, name, global_summary, conclusion,
                     model_key, model_id, model_label,
                     msg_count, total_chars, n_physical_segments,
                     n_segments, n_relations,
                     elapsed_total_s, total_errors,
                     steps_json, errors_json, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (conv_id,
                 result.get("name", ""),
                 result.get("global_summary"),
                 result.get("conclusion"),
                 result.get("model_key", ""),
                 result.get("model_id", ""),
                 result.get("model_label", ""),
                 result.get("msg_count", 0),
                 result.get("total_chars", 0),
                 result.get("n_physical_segments", 0),
                 len(segments),
                 len(relations),
                 result.get("elapsed_total_s", 0),
                 result.get("total_errors", 0),
                 json.dumps(result.get("steps", []), ensure_ascii=False),
                 json.dumps(result.get("errors", []), ensure_ascii=False),
                 result.get("source", ""),
                 now)
            )

            # 2. conv_segments — 段级（先清后写）
            self.cm.conn.execute(
                "DELETE FROM conv_segments WHERE conv_id=?", (conv_id,))
            for i, seg in enumerate(segments):
                span = seg.get("msg_span") or [None, None]
                self.cm.conn.execute(
                    """INSERT INTO conv_segments
                        (conv_id, seg_idx, name, msg_span_start, msg_span_end,
                         summary, complete, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (conv_id, i,
                     seg.get("name", ""),
                     span[0], span[1],
                     seg.get("summary", ""),
                     1 if seg.get("complete") is not False else 0,
                     result.get("source", ""))
                )

            # 3. conv_relations — 关系（先清后写）
            self.cm.conn.execute(
                "DELETE FROM conv_relations WHERE conv_id=?", (conv_id,))
            for r in relations:
                self.cm.conn.execute(
                    """INSERT INTO conv_relations
                        (conv_id, from_idx, to_idx, rel_type, source)
                        VALUES (?, ?, ?, ?, ?)""",
                    (conv_id, r["from"], r["to"],
                     r.get("type", ""),
                     r.get("source", "segment"))
                )

            self.cm.conn.commit()
        except Exception:
            self.cm.conn.rollback()
            raise

    def _load_result(self, conv_id: str) -> Optional[dict]:
        """从三张表重建结果 dict，用于 skip-done 检查"""
        row = self.cm.conn.execute(
            "SELECT * FROM conv_index WHERE conv_id=?", (conv_id,)
        ).fetchone()
        if not row:
            return None

        result = dict(row)
        # 重建 segments
        seg_rows = self.cm.conn.execute(
            "SELECT * FROM conv_segments WHERE conv_id=? ORDER BY seg_idx",
            (conv_id,)
        ).fetchall()
        result["final_segments"] = [
            {
                "name": s["name"],
                "msg_span": [s["msg_span_start"], s["msg_span_end"]],
                "summary": s["summary"],
                "complete": bool(s["complete"]),
            }
            for s in seg_rows
        ]
        # 重建 relations
        rel_rows = self.cm.conn.execute(
            "SELECT * FROM conv_relations WHERE conv_id=?", (conv_id,)
        ).fetchall()
        result["final_relations"] = [
            {"from": r["from_idx"], "to": r["to_idx"], "type": r["rel_type"]}
            for r in rel_rows
        ]
        # 解析 JSON 字段
        try:
            result["steps"] = json.loads(result.get("steps_json") or "[]")
        except (json.JSONDecodeError, ValueError):
            result["steps"] = []
        try:
            result["errors"] = json.loads(result.get("errors_json") or "[]")
        except (json.JSONDecodeError, ValueError):
            result["errors"] = []

        return result

    # ── 核心：索引单个对话 ───────────────────────────

    async def index_conversation(self, conv_id: str, model_key: str = "27b") -> dict:
        """索引单个对话，返回完整结果 dict"""
        profile = MODEL_PROFILES.get(model_key)
        if not profile:
            return {"conv_id": conv_id, "error": f"未知模型 key: {model_key}"}

        # 解析模型路由
        if "model_override" in profile:
            model_override = profile["model_override"]
        else:
            model_override = f"llamaswap:{profile['model_id']}"

        # 加载消息
        msgs = _load_messages(self.cm.conn, conv_id)
        if len(msgs) < 2:
            return {"conv_id": conv_id, "skipped": "too few messages"}

        # 附加 1-based 索引
        for i, m in enumerate(msgs):
            if "sequence" not in m:
                m["sequence"] = i
            m["_1based_idx"] = m["sequence"] + 1

        # 物理分段
        segments = _split_long_conversation(msgs)
        total_chars = sum(len(m.get("text", "")) for m in msgs)
        n_steps = len(segments)

        # 获取对话名称和来源
        conv_row = self.cm.conn.execute(
            "SELECT name, source_type FROM conversations WHERE id=?", (conv_id,)
        ).fetchone()
        conv_name = (conv_row["name"] if conv_row else "") or ""
        conv_source = (conv_row["source_type"] if conv_row else "") or ""

        result = {
            "conv_id": conv_id,
            "source": conv_source,
            "model_key": model_key,
            "model_id": profile.get("model_id", profile.get("model_override", "?")),
            "model_label": profile["label"],
            "name": conv_name[:80],
            "msg_count": len(msgs),
            "total_chars": total_chars,
            "n_physical_segments": n_steps,
            "method": "unified",
            "steps": [],
            "final_segments": [],
            "final_relations": [],
            "global_summary": None,
            "conclusion": None,
            "elapsed_total_s": 0,
            "total_errors": 0,
            "errors": [],
        }

        t_start = time.time()

        # 加载 system prompt
        try:
            sys_prompt = self.pm.build("conv_unified")
        except (ValueError, KeyError):
            fallback_path = config.PROMPTS_DIR / "conv_unified.md"
            if fallback_path.exists():
                sys_prompt = fallback_path.read_text(encoding="utf-8")
            else:
                sys_prompt = "你是一个对话分析工具。请分析对话并输出结构化 JSON。"

        # 滚动处理状态
        completed = []
        pending = None
        all_relations = []
        seen_rel_keys = set()

        for si, seg in enumerate(segments):
            seg_indices = set(m["_1based_idx"] for m in seg)

            if pending:
                unique_pending = [m for m in pending["messages"]
                                  if m["_1based_idx"] not in seg_indices]
            else:
                unique_pending = []

            all_input_indices = set(m["_1based_idx"] for m in unique_pending + seg)
            user_msg = _build_user_prompt(seg, pending, completed, all_relations, is_last_step=False)

            t0 = time.time()
            raw = None
            parsed = None
            quality_ok = False
            max_retries = 3

            for attempt in range(max_retries):
                try:
                    raw = await self.router.chat(
                        prompt=user_msg,
                        system=sys_prompt,
                        model_override=model_override,
                        think=False,
                        num_predict=3072,
                        timeout=300,
                        format=self._schema,
                        source_tag="conv_indexer",
                        sampling_override={"repeat_penalty": 1.3} if attempt > 0 else {"repeat_penalty": 1.1},
                    )
                except Exception as e:
                    result["errors"].append(f"\u6bb5{si+1} \u8c03\u7528\u5931\u8d25: {e}")
                    result["total_errors"] += 1
                    print(f"      \u6bb5{si+1}/{n_steps} FAILED: {e}")
                    break

                parsed = safe_json_parse(raw)
                if not isinstance(parsed, dict):
                    parsed = {}
                    if attempt < max_retries - 1:
                        print(f"        重试 {attempt+1}/{max_retries}: JSON解析失败")
                        continue
                    result["errors"].append(f"\u6bb5{si+1} JSON \u89e3\u6790\u5f02\u5e38")
                    result["total_errors"] += 1
                    break

                # 质量检测
                q_errs = _check_quality(parsed, raw or "")
                if not q_errs:
                    quality_ok = True
                    break

                if attempt < max_retries - 1:
                    print(f"        重试 {attempt+1}/{max_retries}: {'; '.join(q_errs[:2])}")
                else:
                    result["errors"].append(f"\u6bb5{si+1} 质量不过: {'; '.join(q_errs[:2])}")
                    result["total_errors"] += 1

            elapsed = round(time.time() - t0, 1)

            if not parsed:
                parsed = {}

            segs_out = parsed.get("segments") or []
            rels_out = parsed.get("relations") or []

            step_errs = _validate_step(parsed, all_input_indices,
                                       len(completed)) if parsed else ["\u89e3\u6790\u5931\u8d25"]
            result["total_errors"] += len(step_errs)

            n_complete = sum(1 for s in segs_out
                             if isinstance(s, dict) and s.get("complete") is not False)
            n_pending = sum(1 for s in segs_out
                            if isinstance(s, dict) and s.get("complete") is False)

            step_info = {
                "step": si + 1,
                "is_review": False,
                "seg_range": f"{min(seg_indices)}-{max(seg_indices)}",
                "had_pending": pending is not None,
                "elapsed_s": elapsed,
                "n_complete": n_complete,
                "n_pending": n_pending,
                "n_relations": len(rels_out),
                "errors": step_errs,
                "raw_response_len": len(raw) if raw else 0,
            }
            result["steps"].append(step_info)

            err_mark = "\u2713" if not step_errs else f"\u26a0{len(step_errs)}"
            print(f"      \u6bb5{si+1}/{n_steps} {elapsed}s {err_mark} | "
                  f"{n_complete}\u5b8c + {n_pending}\u7eed + {len(rels_out)}\u5173\u7cfb")

            # 收集 relations（去重）
            for r in rels_out:
                if (isinstance(r, dict)
                        and isinstance(r.get("from"), int)
                        and isinstance(r.get("to"), int)):
                    key = (r["from"], r["to"])
                    if key not in seen_rel_keys:
                        seen_rel_keys.add(key)
                        all_relations.append({
                            "from": r["from"],
                            "to": r["to"],
                            "type": r.get("type", ""),
                            "source": "segment",
                        })

            # 更新 pending/complete 状态
            max_seen = max(all_input_indices) if all_input_indices else 0
            min_seen = min(all_input_indices) if all_input_indices else 0
            pending = None

            for s in segs_out:
                if not isinstance(s, dict):
                    continue
                span = s.get("msg_span") or [None, None]
                # 修正越界 span
                if span[0] is not None and span[0] < min_seen:
                    span[0] = min_seen
                if span[1] is not None and span[1] > max_seen:
                    s["complete"] = False
                    span[1] = None

                if s.get("complete") is False:
                    span_start = span[0] if span[0] else min_seen
                    # 只带当前段的未完结消息，不累积历史pending（否则越攒越大撑爆context）
                    pending_msgs = [m for m in seg
                                    if m["_1based_idx"] >= span_start]
                    pending = {
                        "name": s.get("name", ""),
                        "msg_span_start": span_start,
                        "summary": s.get("summary", ""),
                        "messages": pending_msgs,
                    }
                else:
                    completed.append({
                        "name": s.get("name", ""),
                        "msg_span": span,
                        "summary": s.get("summary", ""),
                    })

        # pending 强制完成
        if pending:
            pending_end = msgs[-1]["_1based_idx"]
            completed.append({
                "name": pending["name"],
                "msg_span": [pending["msg_span_start"], pending_end],
                "summary": pending["summary"],
            })

        # 覆盖检查：确保每条消息都被某段覆盖
        covered = set()
        for t in completed:
            if t["msg_span"][0] and t["msg_span"][1]:
                covered.update(range(t["msg_span"][0], t["msg_span"][1] + 1))
        all_ids = set(range(1, len(msgs) + 1))
        uncovered = sorted(all_ids - covered)
        if uncovered and completed:
            for mid in uncovered:
                best = min(completed,
                           key=lambda t: abs((t["msg_span"][0] or 999) - mid))
                old_s, old_e = best["msg_span"]
                best["msg_span"] = [min(old_s, mid), max(old_e, mid)]

        result["final_segments"] = completed

        # ── 全局回顾步骤 ──
        if not completed:
            # 寒暄/无信息量对话，跳过回顾
            result["global_summary"] = None
            result["conclusion"] = None
            result["final_relations"] = []
            result["elapsed_total_s"] = round(time.time() - t_start, 1)
            self._save_result(conv_id, result)
            return result

        review_msg = _build_review_prompt(completed, all_relations)
        t0 = time.time()

        # 回顾步骤也带重试+质量检测
        parsed_review = None
        review_quality_ok = False
        for attempt in range(max_retries):
            try:
                raw_review = await self.router.chat(
                    prompt=review_msg,
                    system=sys_prompt,
                    model_override=model_override,
                    think=False,
                    num_predict=2048,
                    timeout=300,
                    format=self._schema,
                    source_tag="conv_indexer",
                    sampling_override={"repeat_penalty": 1.3} if attempt > 0 else {"repeat_penalty": 1.1},
                )
            except Exception as e:
                result["errors"].append(f"回顾步骤失败: {e}")
                result["total_errors"] += 1
                break

            parsed_review = safe_json_parse(raw_review)
            if not isinstance(parsed_review, dict):
                if attempt < max_retries - 1:
                    print(f"        回顾重试 {attempt+1}/{max_retries}: JSON解析失败")
                    continue
                result["errors"].append("回顾步骤 JSON 解析异常")
                result["total_errors"] += 1
                break

            q_errs = _check_quality(parsed_review, raw_review or "")
            if not q_errs:
                review_quality_ok = True
                break
            if attempt < max_retries - 1:
                print(f"        回顾重试 {attempt+1}/{max_retries}: {'; '.join(q_errs[:2])}")
            else:
                result["errors"].append(f"回顾质量不过: {'; '.join(q_errs[:2])}")
                result["total_errors"] += 1

        elapsed_review = round(time.time() - t0, 1)

        if isinstance(parsed_review, dict):
            review_errs = _validate_step(parsed_review, set(),
                                         len(completed), is_review_step=True)
            result["total_errors"] += len(review_errs)

            result["global_summary"] = parsed_review.get("global_summary")
            result["conclusion"] = parsed_review.get("conclusion")

            # 补充远距离关系
            new_rels = 0
            for r in (parsed_review.get("relations") or []):
                if (isinstance(r, dict)
                        and isinstance(r.get("from"), int)
                        and isinstance(r.get("to"), int)):
                    key = (r["from"], r["to"])
                    if key not in seen_rel_keys:
                        seen_rel_keys.add(key)
                        all_relations.append({
                            "from": r["from"],
                            "to": r["to"],
                            "type": r.get("type", ""),
                            "source": "review",
                        })
                        new_rels += 1

            err_mark = "\u2713" if not review_errs else f"\u26a0{len(review_errs)}"
            gs = result["global_summary"] or ""
            print(f"      \u56de\u987e {elapsed_review}s {err_mark} | "
                  f"+{new_rels}\u8fdc\u8ddd\u5173\u7cfb | summary {len(gs)}\u5b57")

            result["steps"].append({
                "step": n_steps + 1,
                "is_review": True,
                "elapsed_s": elapsed_review,
                "n_new_relations": new_rels,
                "errors": review_errs,
            })
        else:
            result["errors"].append("回顾步骤解析失败")
            result["total_errors"] += 1

        result["final_relations"] = all_relations
        result["elapsed_total_s"] = round(time.time() - t_start, 1)
        result["coverage_gaps"] = len(uncovered) if uncovered else 0

        # 增量存储
        self._save_result(conv_id, result)

        return result

    # ── Keepalive ────────────────────────────────────

    async def _keepalive(self, model_override: str):
        """发送轻量请求保持模型在内存，防止 TTL 卸载"""
        try:
            await self.router.chat(
                prompt="ok",
                model_override=model_override,
                num_predict=1,
                timeout=30,
                source_tag="conv_indexer_keepalive",
            )
            self._last_keepalive = time.time()
        except Exception:
            pass  # keepalive 失败不影响主流程

    # ── 批量索引 ─────────────────────────────────────

    async def index_all(self, limit: int = 0, model_key: str = "27b",
                         force: bool = False) -> dict:
        """批量索引所有对话，跳过已完成的（除非 force=True）"""
        profile = MODEL_PROFILES.get(model_key)
        if not profile:
            return {"error": f"\u672a\u77e5\u6a21\u578b key: {model_key}"}

        # 解析模型路由（keepalive 用）
        if "model_override" in profile:
            model_override = profile["model_override"]
        else:
            model_override = f"llamaswap:{profile['model_id']}"

        # 分步查询：先拿全部对话和已索引集合，再用Python过滤（避免慢子查询）
        all_rows = self.cm.conn.execute(
            "SELECT id, name, total_chars, message_count FROM conversations ORDER BY total_chars ASC"
        ).fetchall()

        if not force:
            indexed_ids = set(r[0] for r in self.cm.conn.execute("SELECT conv_id FROM conv_index").fetchall())
            all_convs = [dict(r) for r in all_rows if r["id"] not in indexed_ids]
        else:
            all_convs = [dict(r) for r in all_rows]

        # 过滤实际消息数（元数据不准，按真实消息数判断）
        _filtered = []
        for conv in all_convs:
            actual = self.cm.conn.execute(
                "SELECT COUNT(*) FROM conversation_messages WHERE conversation_id = ?",
                (conv["id"],)
            ).fetchone()[0]
            if actual >= 2:
                _filtered.append(conv)
        all_convs = _filtered
        print(f"[conv_indexer] 过滤后剩余: {len(all_convs)}/{len(all_rows)} 个对话")

        if limit > 0:
            all_convs = all_convs[:limit]

        self._batch_total = len(all_convs)
        self._batch_done = 0
        self._batch_start_time = time.time()
        self._last_keepalive = time.time()

        results = {"completed": [], "skipped": [], "errors": [],
                   "model_key": model_key, "model_label": profile["label"]}

        print(f"\n[conv_indexer] \u5f00\u59cb\u6279\u91cf\u7d22\u5f15: {self._batch_total} \u4e2a\u5bf9\u8bdd | \u6a21\u578b: {profile['label']}")

        for ci, conv in enumerate(all_convs):
            conv_id = conv["id"]
            conv_name = (conv.get("name") or "")[:60]

            t0 = time.time()
            try:
                result = await self.index_conversation(conv_id, model_key)
            except Exception as e:
                elapsed = round(time.time() - t0, 1)
                self._batch_done += 1
                results["errors"].append({
                    "conv_id": conv_id,
                    "name": conv_name,
                    "error": str(e),
                    "elapsed_s": elapsed,
                })
                print(f"[{self._batch_done}/{self._batch_total}] {model_key} | "
                      f"{conv_name} | {elapsed}s | FAILED: {e}")
                continue

            elapsed = result.get("elapsed_total_s", round(time.time() - t0, 1))
            self._batch_done += 1
            n_segs = len(result.get("final_segments") or [])
            n_rels = len(result.get("final_relations") or [])
            n_errors = result.get("total_errors", 0)

            if result.get("skipped"):
                results["skipped"].append({
                    "conv_id": conv_id,
                    "name": conv_name,
                    "reason": result["skipped"],
                })
            else:
                results["completed"].append({
                    "conv_id": conv_id,
                    "name": conv_name,
                    "n_segments": n_segs,
                    "n_relations": n_rels,
                    "elapsed_s": elapsed,
                    "errors": n_errors,
                })

            print(f"[{self._batch_done}/{self._batch_total}] {model_key} | "
                  f"{conv_name} | {elapsed}s | "
                  f"{n_segs}\u6bb5+{n_rels}\u5173\u7cfb"
                  + (f" | \u26a0{n_errors}\u9519\u8bef" if n_errors else ""))

            # 模型刚被调过，重置 keepalive 计时
            self._last_keepalive = time.time()

        # 汇总统计
        total_elapsed = round(time.time() - self._batch_start_time, 1)
        results["total_elapsed_s"] = total_elapsed
        results["n_completed"] = len(results["completed"])
        results["n_skipped"] = len(results["skipped"])
        results["n_errors"] = len(results["errors"])

        print(f"\n[conv_indexer] \u6279\u91cf\u7d22\u5f15\u5b8c\u6210: "
              f"{results['n_completed']}\u5b8c\u6210 + "
              f"{results['n_skipped']}\u8df3\u8fc7 + "
              f"{results['n_errors']}\u5931\u8d25 | "
              f"\u603b\u8017\u65f6 {total_elapsed}s")

        return results

    # ── 批量嵌入 ─────────────────────────────────────

    def batch_embed_summaries(self, batch_size: int = 24) -> dict:
        """批量嵌入所有未嵌入的段摘要 + 全局摘要（BGE-M3 dense + sparse）"""
        import json as _json
        from core.embedding import get_embedding
        bge = get_embedding()
        results = {"segments": 0, "global_summaries": 0}

        # 1. 嵌入 conv_segments: name + summary
        rows = self.cm.conn.execute("""
            SELECT id, name, summary FROM conv_segments
            WHERE summary != '' AND embedding IS NULL
        """).fetchall()

        if rows:
            texts = []
            for r in rows:
                name = (r["name"] or "").strip()
                summary = (r["summary"] or "").strip()
                texts.append(f"{name}：{summary}" if name else summary)

            total = len(texts)
            print(f"[embed] 段摘要: {total} 条待嵌入 (batch={batch_size})")
            t0 = time.time()

            for i in range(0, total, batch_size):
                batch_texts = texts[i:i + batch_size]
                batch_rows = rows[i:i + batch_size]
                dense, sparse_list = bge.embed_dense_sparse(
                    batch_texts, batch_size=len(batch_texts))

                for j, r in enumerate(batch_rows):
                    blob = bge.vec_to_blob(dense[j])
                    sw = sparse_list[j]
                    sparse_str = _json.dumps(
                        {k: float(v) for k, v in sw.items()},
                        ensure_ascii=False,
                    ) if sw else None
                    self.cm.conn.execute(
                        "UPDATE conv_segments SET embedding = ?, sparse_vector = ? WHERE id = ?",
                        (blob, sparse_str, r["id"]),
                    )
                self.cm.conn.commit()
                done = min(i + batch_size, total)
                elapsed = time.time() - t0
                eta = elapsed / done * (total - done) if done else 0
                print(f"  {done}/{total} {elapsed:.0f}s ETA {eta/60:.1f}min")

            results["segments"] = total
            print(f"[embed] 段摘要完成: {total} 条, {time.time()-t0:.0f}s")

        # 2. 嵌入 conv_index: global_summary
        rows = self.cm.conn.execute("""
            SELECT conv_id, global_summary FROM conv_index
            WHERE global_summary IS NOT NULL AND global_summary != ''
              AND embedding IS NULL
        """).fetchall()

        if rows:
            texts = [r["global_summary"] for r in rows]
            total = len(texts)
            print(f"[embed] 全局摘要: {total} 条待嵌入")
            t0 = time.time()

            for i in range(0, total, batch_size):
                batch_texts = texts[i:i + batch_size]
                batch_rows = rows[i:i + batch_size]
                dense, sparse_list = bge.embed_dense_sparse(
                    batch_texts, batch_size=len(batch_texts))

                for j, r in enumerate(batch_rows):
                    blob = bge.vec_to_blob(dense[j])
                    sw = sparse_list[j]
                    sparse_str = _json.dumps(
                        {k: float(v) for k, v in sw.items()},
                        ensure_ascii=False,
                    ) if sw else None
                    self.cm.conn.execute(
                        "UPDATE conv_index SET embedding = ?, sparse_vector = ? WHERE conv_id = ?",
                        (blob, sparse_str, r["conv_id"]),
                    )
                self.cm.conn.commit()
                done = min(i + batch_size, total)
                elapsed = time.time() - t0
                eta = elapsed / done * (total - done) if done else 0
                print(f"  {done}/{total} {elapsed:.0f}s ETA {eta/60:.1f}min")

            results["global_summaries"] = total
            print(f"[embed] 全局摘要完成: {total} 条, {time.time()-t0:.0f}s")

        if not results["segments"] and not results["global_summaries"]:
            print("[embed] 全部已嵌入，无需处理")
        return results

    # ── 状态报告 ─────────────────────────────────────

    def get_status(self) -> dict:
        """返回当前索引进度报告"""
        # 查所有对话数
        total_convs = self.cm.conn.execute(
            "SELECT COUNT(*) FROM conversations"
        ).fetchone()[0]

        # 查已索引数
        indexed = self.cm.conn.execute(
            "SELECT COUNT(*) FROM conv_index"
        ).fetchone()[0]

        # 查已索引的详细统计
        row = self.cm.conn.execute("""
            SELECT model_key,
                   COUNT(*) as cnt,
                   SUM(n_segments) as total_segs,
                   SUM(n_relations) as total_rels,
                   SUM(elapsed_total_s) as total_time
            FROM conv_index
            GROUP BY model_key
        """).fetchall()

        model_dist = {}
        total_segs = 0
        total_rels = 0
        total_time = 0.0
        for r in row:
            model_dist[r[0]] = r[1]
            total_segs += r[2] or 0
            total_rels += r[3] or 0
            total_time += r[4] or 0

        status = {
            "total_conversations": total_convs,
            "indexed": indexed,
            "pending": total_convs - indexed,
            "total_segments": total_segs,
            "total_relations": total_rels,
            "total_indexing_time_s": round(total_time, 1),
            "model_distribution": model_dist,
        }

        # 如果正在批量处理，加上进度
        if self._batch_total > 0:
            status["batch"] = {
                "done": self._batch_done,
                "total": self._batch_total,
                "elapsed_s": round(time.time() - self._batch_start_time, 1)
                if self._batch_start_time else 0,
            }

        return status
