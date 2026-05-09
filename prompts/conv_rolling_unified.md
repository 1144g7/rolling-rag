# 统一滚动提示词草案（讨论用，不替换现有文件）

## 核心变化

### 和当前方案的差异

| | 当前（三段式） | 统一（一段式） |
|---|---|---|
| 短对话 | conv_summary 独立提示词 | 滚动一步，等价 conv_summary |
| 长对话滚动 | conv_rolling，只输出 segments + local relations | 同左，但 relations 可引用已完成段（全局下标） |
| 长对话综合 | conv_synthesis，额外产生 summary + conclusion + extra_relations | 最后一步时由滚动提示词直接输出 summary + conclusion |
| 关系精度 | 滚动只标相邻，综合补跨段 | 每步都能标跨段关系（因为已有所有摘要） |
| 提示词数量 | 3 个 | 1 个 + schema 约束 |

### 输出 Schema 变化

```json
{
  "segments": [...],       // 同现在
  "relations": [...],      // from/to 用全局下标（见下）
  "summary": null,         // 只有最后一步才填，其余为 null
  "conclusion": null       // 只有最后一步才填，其余为 null
}
```

## 关键设计问题

### 1. relations 的下标系统

当前：from/to 是本步输出内的局部下标（0-based）
统一：from/to 是**全局下标**

已完成段列表：[seg_0, seg_1, ..., seg_{N-1}]
本步新输出段：将追加为 [seg_N, seg_{N+1}, ...]

模型在 prompt 中被告知："已完成段共 N 个，下标 0 到 N-1。你输出的新段将从 N 开始编号。relations 的 from/to 可以引用已完成段（0 到 N-1）或新段（N 起）。"

代码侧：本步输出 segments 后，全局下标 = len(completed) + local_index

### 2. summary / conclusion 何时输出

在 user prompt 中明确告知：
- 中间步：`"这是第 X/Y 段，只输出 segments 和 relations"`
- 最后步：`"这是最后一段，请额外输出 summary 和 conclusion"`

模型不需要自己判断是否最后一步，由代码控制。

### 3. 已完成摘要列表的膨胀

41 段 → 40 × 200 字 = 8000 字 ≈ 2700 token（OK）
极端 120 段 → 120 × 200 字 = 24000 字 ≈ 8000 token（仍 OK，27B 模型 32K 上下文）

如果超过上下文限制：
- 截断最早的摘要（保留最近 30 条完整 + 更早的只留 name + msg_span）
- 或分批综合（把 120 段分 3 批，每批 40 段先局部综合，再全局综合）
- 这是极端情况，可以后续处理

### 4. 和短对话的兼容

短对话（≤12K chars）只滚一步：
- 没有 completed，没有 pending
- 输入就是完整对话
- 输出 summary + conclusion + segments + relations
- 等价于当前的 conv_summary

提示词只需判断：如果 completed 为空且没有 pending，则说明是第一步（可能是唯一一步）。

## 潜在问题

### P1: 最后一步的输出 token 会不会不够？

当前 num_predict=4096。如果最后一步要输出：
- 当前段的新 segments（~5 个 × 300 字 = 1500 字）
- 跨段 relations（~10 条 × 20 字 = 200 字）
- summary（可能 1000+ 字）
- conclusion（50 字）

总计 ~3000 字 ≈ 3000 token（中文 1 char ≈ 1 token 在输出侧偏高）

4096 可能勉强够，但安全起见最后一步可以给 num_predict=8192。

### P2: 关系去重

如果段 1 标了 seg0→seg2，段 3 又标了一次 seg0→seg2，需要代码去重。
按 (from, to) 去重即可，保留第一次的 type。

### P3: conclusion 的质量

当前综合阶段只看摘要写 conclusion。统一方案里最后一步同时看摘要 + 当前段原文，
其实信息更多，conclusion 质量应该更好。

### P4: prompt 会不会太复杂？

统一提示词需要覆盖：短对话 / 滚动中间步 / 滚动最后步，三种场景。
条件逻辑多了可能让模型困惑。解法：把场景判断交给代码（在 user prompt 里明确说"你是第几步/共几步"），
提示词本身只定义一种输出格式。
