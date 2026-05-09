# Rolling RAG

> **From two screenshots to a core logic: how to make AI remember all your conversations.**

[中文](#中文)

---

## Origin

March 2026. I was building a screen analysis module — I needed AI to analyze my entire screen activity and output a daily log.

The hard part: sending screenshots one by one couldn't maintain continuous context. Batch sending couldn't get the boundaries right either — if I was reading articles on a website and switched to a new one, without handling the boundary, I couldn't capture each article as a complete unit.

My first solution: rolling transmission — send two overlapping frames, "A+B" then "B+C", so the AI always sees the previous context alongside the current frame.

I complained to the AI that this was too slow. Its response changed everything:

> **"Don't send two images. Just send the description of the previous frame to the next one."**

That moment I realized: **I don't need the original — a description/summary can link context.**

Raw data (images/conversations/articles) is raw material. Summaries are portable structure. The previous segment's summary flows into the next — that's "rolling".

I immediately migrated this pattern from screenshots to conversations: original text = image, summary = description, summary flowing into the next segment = rolling window. Then I discovered — **it applies to anything that needs context continuity.** Like AI voice input, AI translation...

Three months later, this idea was validated on 4,881 real conversations. I added typed relationships to solve the linking problem between semantic segments, fully utilized KV cache and batch acceleration for ultra-long contexts, and used XML prompts to improve accuracy.

---

## Core Idea

Existing RAG solutions focus on "how to cut" and "how to find". Rolling RAG already handles cutting well — it focuses on **"how to connect"**:

```
Unstructured conversation
    ↓
① Semantic segmentation — don't cut by token count, ask LLM "where does the topic change"
    ↓
② Rolling window — each window sees the last 2 segments + accumulated summaries, no breaks at boundaries
    ↓
③ Relationship extraction — 12 typed relations using summaries + current text (experimental)
    ↓
④ Global summary — one summary per physical boundary, focusing on narrative arcs and relations, not chat details
    ↓
⑤ Multi-perspective re-rolling — cluster by vectors, re-roll from specific perspectives, build cross-segment relations, extract per-perspective global summaries
    ↓
Structured memory network
```

Key insight: **People don't remember every word — they remember the key points, and can expand when needed.** Each level is a compressed view of the level below.

---

## One Prompt, Two Modes

The core logic lives in a single prompt. You don't need our code — any LLM + any vector database, just follow the prompt.

> Full prompt: [`prompts/conv_unified.md`](prompts/conv_unified.md)

### Mode A — Per-Segment Processing

Receives: current conversation segment text + list of completed segment summaries → Outputs: new segment summaries + inter-segment relationships.

Core mechanisms:

- **Semantic boundary detection**: same goal with different methods = not a new segment; branching to a different topic = new segment
- **Rolling context**: each window sees the last 2 segment summaries, no breaks at boundaries
- **Unfinished segment continuation**: merge incomplete segments across physical boundaries
- **12 typed relationships**: 6 core (prerequisite/causal/evolution/application/contrast/instance) + 6 extended
- **Prefix cache optimization**: completed segment summaries + relations as growing prefix, never breaks KV cache. Only the current segment text (variable) changes per step

### Mode B — Global Review

Receives: all segment summaries → Outputs: global summary + conclusion + long-distance relationships.

Core mechanisms:

- **Coverage-style summary**: exhaustively preserve all key entities (tool names, versions, numbers, conclusions). Don't sacrifice entities for brevity — if it's missing, it can't be searched
- **Long-distance relationship supplement**: only add relations between segments ≥3 apart; nearby relations already annotated in Mode A

### Output Structure

One prompt + one fixed JSON Schema, shared by both modes:

```json
{
  "segments": [
    {
      "name": "Snow pot material selection",
      "msg_span": [1, 4],
      "summary": "User asks about snow pots (titanium, stainless steel) for solo cooking. AI recommends pure titanium or 316 stainless steel, designs 'subtractive cooking': one-pot blanch-and-sauce, ready-made carbs with pan-fried protein, modular meal prep to minimize dishwashing.",
      "complete": true
    },
    {
      "name": "Air fryer introduction",
      "msg_span": [5, 10],
      "summary": "User confirms need for air fryer. AI affirms it replaces oven/microwave efficiently. Recommends: paper-wrapped cooking, sous vide, emulsion pasta, pressure cooker, modular Buddha bowls. User shows strong interest in 'systems thinking' cooking.",
      "complete": true
    },
    {
      "name": "Air fryer vs oven analysis",
      "msg_span": [11, 12],
      "summary": "User distinguishes air fryer from oven. AI explains both use heat transfer, but air fryer is 'aggressive convection' (simulates frying, no preheat), ideal for solo efficiency; oven excels at moist baking (chiffon) and large batches. Conclusion: air fryer wins for non-baker singles.",
      "complete": true
    }
  ],
  "relations": [
    {"from": 0, "to": 2, "type": "prerequisite"},
    {"from": 1, "to": 2, "type": "evolution"}
    // from/to use global indices: completed segments 0~N-1, new segments start from N
  ],
  "global_summary": "Omit in Mode A. Fill with coverage-style global summary in Mode B.",
  "conclusion": "Omit in Mode A. Fill with one-sentence endpoint in Mode B."
}
```

Relationship types:

- **Core**: prerequisite (B needs A first) | causal (A causes B) | evolution (A develops into B) | application (A applied to B) | contrast (A and B are alternatives/opposites) | instance (B is a concrete example of A)
- **Extended**: contains | derives | usage | equivalent | contradicts | temporal

---

## How to Implement

```
1. Collect conversation data
2. Split by physical length (e.g. every 8000 chars, with overlap)
3. Use the prompt (Mode A) per chunk — each chunk produces multiple semantic segment summaries + relationships
4. After all chunks processed, use the prompt (Mode B) for global review — global summary + long-distance relationships
5. Embed segment summaries into vector database
6. Query: semantic search → return segment summaries → expand original text as needed
```

That's it. The core logic is all in the prompt.

---

## Comparison

| | Graph RAG | Mem0 | **Rolling RAG** |
|---|:-:|:-:|:-:|
| Memory unit | Entity | Fact | **Segment** |
| Structure | Entity graph | Vector + graph | **Relationship network** |
| Boundary detection | None | None | **Semantic (LLM)** |
| Relation types | Generic | Generic | **12 typed** |
| Multi-level abstraction | ❌ | ❌ | **✅ Rolling** |
| Overlap continuity | ❌ | ❌ | **✅ overlap=2** |

The biggest difference: Graph RAG builds **a graph of entities** (who mentioned whom). Rolling RAG builds **a network of ideas** (how did this conclusion come about, and why).

---

## Status

Core logic validated in a full perception engine (4,881 conversations / 7,996 segments / 5,119 relations).

MCP Server version in development — will be released as a standalone product supporting Claude Code, Cursor, and other MCP-compatible clients.

## License

MIT

---

# 中文

> **从两张截图到一个核心逻辑：如何让AI记住你所有的对话**

[English](#rolling-rag)

---

## 起源

2026年3月。我在做一个屏幕分析模块，需要AI分析我的一整天的屏幕做记录并且输出日志。

有一个很难的点是：一张一张发送给AI做不到连续的上下文，批量去送也不一定可以送对正确的边界，比如我在看知乎看着看着换了一篇，如果我没有处理边界问题，那我就没办法把单独的一篇文字给完整的记录下来，当时想到的解决办法是：
滚动传送，一次发两张，「A+B」+「B+C」发送临近的上文给到AI，然后在文章切换的时候做一个标记，这样我就可以完整的去切割我看的内容的边界了。

我给AI抱怨说了一句这样太慢了AI给的回复是：

> **"不用发两张图。把上一帧的描述送入下一帧就行。"**

那一刻我意识到：**我不需要原图，描述摘要就可以链接上下文。**

原始数据（图片/对话/文章）是原料。摘要是可搬运的结构。上一段的摘要流入下一段——这就是"滚动"。

我立刻把这个模式从截图迁移到对话：原文=图片，摘要=描述，摘要流入下一段=滚动窗口。然后我发现——**它适用于任何需要上下文关联的东西**。**比如AI语音输入法，AI翻译...**

三个月后，这个想法在 4,881 条真实对话上跑出了结果，并且我加入了关系链试图解决语义段落之间的链接问题。
充分利用KV cache和批量加速处理超长上下文，并用xml提示词提高了准确度。

---

## 核心思想

现有的RAG方案都在处理"怎么切"和"怎么找"。Rolling RAG因为已经把切好了，现阶段处理的是**"怎么连"**：

```
无序对话
    ↓
① 语义分段 — 不按token数硬切，问LLM"话题在哪里变了"
    ↓
② 滚动窗口 — 每个窗口看前一个窗口的最后2段和累计的摘要，不在边界处断裂
    ↓
③ 关系提取 — 利用摘要和当前原文做12种类型化关系（实验版）
    ↓
④ 全局摘要 — 一个大的物理边界的总结，主要看叙事线和关系，不看具体聊天内容
    ↓
⑤ 多视角重滚 — 根据向量聚类某些特定视角重新滚一遍，建立跨段关系，提取该视角的全局摘要，提高召回权重
    ↓
结构化记忆网络
```

关键洞察：**人不记得每个字，记得要点，需要时可以展开。** 每一层都是下一层的压缩视图。

---

## 一个提示词，两种模式

核心逻辑全在一个提示词里。你不需要我们的代码——用任何LLM + 任何向量数据库，照着提示词做就行。

> 完整提示词：[`prompts/conv_unified.md`](prompts/conv_unified.md)

### 模式A — 逐段处理

收到当前对话段的原文 + 已完成段的摘要列表 → 输出新段的摘要 + 段间关系。

核心机制：

- **语义边界检测**：同一目标换方法不算新段；岔出去聊别的算
- **滚动上下文**：每个窗口看前2段的摘要，保证话题不在边界断裂
- **未完成段延续**：上一段没说完的，合并到下一段
- **12种类型化关系**：核心6种（前提/因果/演进/应用/对比/实例）+ 扩展6种
- **前缀缓存优化**：已完成段的摘要+关系作为前缀逐段追加，不破坏KV cache。每段只变当前段原文（变量部分），前缀部分全命中缓存

### 模式B — 全局回顾

收到全部段摘要 → 输出全局摘要 + 结论 + 补充远距离关系。

核心机制：

- **覆盖式摘要**：穷尽所有关键实体（工具名、版本号、数值、结论），不为精炼丢实体——缺了就搜不到
- **远距离关系补充**：只补距离≥3的跨段关系，近距的已在模式A标注

### 输出结构

一个提示词 + 一个固定的JSON Schema，两种模式共用：

```json
{
  "segments": [
    {
      "name": "雪平锅材质选型与单人食结构",
      "msg_span": [1, 4],
      "summary": "用户询问适合一人食的雪平锅（钛、不锈钢等）及饮食结构。AI推荐纯钛或316不锈钢，并设计'减法烹饪'：利用现有设备（电饭煲/煎锅+新购雪平锅），采用'一锅到底烫肉拌酱'、'现成碳水配煎肉'和'拼图式备菜'，将洗锅量减至最低。",
      "complete": true
    },
    {
      "name": "空气炸锅引入与进阶烹饪流派推荐",
      "msg_span": [5, 10],
      "summary": "用户确认需空气炸锅，AI肯定其整合了烤箱/微波炉的高效。为拓宽认知且健康（防上火），AI推荐：纸包料理（半蒸半烤）、低温慢煮（Sous Vide精准控温与批量备餐）、乳化反应流意面、电压力锅及模块化佛陀碗。用户表示对'系统思维'类烹饪非常感兴趣。",
      "complete": true
    },
    {
      "name": "空气炸锅 vs 烤箱：单人食的最优解论证",
      "msg_span": [11, 12],
      "summary": "用户辨析空炸与烤箱的区别。AI指出本质均为热传递，但空炸是'狂风对流'（模拟油炸口感、无需预热），适合一人食效率；而烤箱在湿润烘焙（戚风）、大体量食材上不可替代。结论：对于不专业烘焙的单人场景，空气炸锅完胜烤箱。",
      "complete": true
    }
  ],
  "relations": [
    {"from": 0, "to": 2, "type": "前提"},
    {"from": 1, "to": 2, "type": "演进"}
  ],
  "global_summary": "模式A时省略。模式B时填覆盖式全局摘要",
  "conclusion": "模式A时省略。模式B时填一句话落点"
}
```

关系类型：

- **核心**：前提（B需要A先成立）| 因果（A导致B）| 演进（A发展成B）| 应用（A用在B场景）| 对比（A和B是替代/对立）| 实例（B是A的具体例子）
- **扩展**：包含 | 衍生 | 用途 | 等价 | 矛盾 | 时序

---

## 如何实现

```
1. 收集对话数据
2. 按物理长度切段（比如每8000字一段，带overlap）
3. 用提示词（模式A）逐段处理，每段产出多个语义段摘要 + 段间关系
4. 全部处理完后，用提示词（模式B）做全局回顾，产出全局摘要 + 远距离关系
5. 段摘要做embedding存入向量数据库
6. 查询时：语义搜索 → 返回段摘要 → 按需展开原文
```

就这么简单。核心逻辑全在提示词里。

---

## 和现有方案的区别

| | Graph RAG | Mem0 | **Rolling RAG** |
|---|:-:|:-:|:-:|
| 记忆单元 | 实体 | 事实 | **段落** |
| 结构 | 实体图谱 | 向量+图谱 | **关系网络** |
| 边界检测 | 无 | 无 | **语义（LLM）** |
| 关系类型 | 泛化 | 泛化 | **12种类型化** |
| 多层抽象 | ❌ | ❌ | **✅ 滚动** |
| 重叠连续性 | ❌ | ❌ | **✅ overlap=2** |

最大的区别：Graph RAG 建的是**实体之间的图**（谁提到了谁），Rolling RAG 建的是**想法之间的网络**（这个结论怎么来的、为什么）。

---

## 状态

核心逻辑在一个完整的感知引擎中运行验证（4,881对话 / 7,996段 / 5,119关系）。

MCP Server 版本正在开发中，将作为独立产品支持 Claude Code / Cursor 等客户端。

## License

MIT
