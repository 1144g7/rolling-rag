# Rolling RAG

> From chaos to structure: rebuilding relationships in unstructured conversations.

## The Problem

LLM context windows are finite. Conversations are infinite.

You talk to AI every day — about frameworks, purchases, decisions, ideas. A month later, it remembers nothing. You search your history and find fragments, but the **connections between them are gone**.

"Which framework did I choose? Why? What happened after?"

## Existing Solutions Fall Short

| Approach | What it does | What it loses |
|----------|-------------|---------------|
| **Simple chunking** | Cut by token count | Splits topics mid-sentence |
| **Compression** | Summarize into shorter text | Loses detail and nuance |
| **Vector search** | Find similar chunks | No structure, no relationships |
| **Graph RAG** | Build entity graphs | Entities ≠ conversation flow |

None of them capture **how ideas evolve across a conversation** — the "why" behind the "what".

## Rolling RAG

Rolling RAG takes a different approach. Instead of compressing or cutting, it **restructures**:

```
Unstructured conversation
        ↓
[1] Semantic boundary detection (not token count)
        ↓
[2] Rolling window with overlap (no hard cuts)
        ↓
[3] Relationship extraction between segments
        ↓
[4] Global summary + conclusion
        ↓
Structured memory network
```

### Step 1: Semantic Boundary Detection

Don't cut at token 4096. Ask the LLM: "Where does the topic change?"

```python
# Physical cut (bad):
[chunk 1: "...I think Python is the right",    # cut mid-sentence
 chunk 2: " choice for this project because..."]

# Semantic cut (good):
[segment 1: "Discussion about language choice → decided Python",
 segment 2: "Project architecture planning → chose microservices"]
```

### Step 2: Rolling Window with Overlap

Each window looks at the last 2 segments of the previous window. This ensures no topic is split at the boundary.

```
Window 1: [msg 1-20]   → segments A, B
Window 2: [msg 18-40]  → segments B(overlap), C, D
Window 3: [msg 38-60]  → segments D(overlap), E, F
```

`overlap=2` means each window reviews the last 2 segments from the previous one. Continuity is preserved.

### Step 3: Relationship Extraction

This is the core. After segmentation, ask: "How do these segments relate to each other?"

12 relationship types:

| Type | Example |
|------|---------|
| **Prerequisite** | "Chose llama-swap" ← "Understood LM Studio limitations" |
| **Causal** | "RAM usage spike" → "Switched to quantized model" |
| **Evolution** | "Draft v1" → "Refined v2" → "Final v3" |
| **Application** | "Learned BGE-M3" → "Applied to search pipeline" |
| **Contrast** | "Considered ChromaDB" vs "Chose SQLite+vector" |
| **Instance** | "General rule: prefer local models" → "Specific: use qwen-35b" |
| **Contains** | "Project planning" contains "model selection" |
| **Derives** | "User preferences" derives from "conversation patterns" |
| **Usage** | "Router module" used by "Agent system" |
| **Equivalent** | "Conv index" ≈ "Memory layer" |
| **Contradicts** | "L1/L2 claims" contradicts "Conv segments approach" |
| **Temporal** | "Before migration" → "After migration" |

### Step 4: Multi-Level Abstraction

Roll up multiple times:

```
Level 0: Raw messages (infinite)
Level 1: Segments + relations (7996 segments, 5119 relations)
Level 2: Global summaries + inter-summary relations (~1899)
Level 3: Cross-conversation patterns (future)
```

Each level is a compressed, structured view of the level below. The AI can navigate up and down.

## Results

Tested on LongMemEval benchmark (500 questions, ~48 sessions each):

| Mode | R@1 | R@3 | R@5 |
|------|-----|-----|-----|
| Dense only | 73.2% | 86.4% | 89.6% |
| + Sparse | 77.2% | 86.0% | 88.8% |
| + Rerank | 77.2% | 87.6% | **90.0%** |

- Sparse search boosts temporal/preference queries by +8-10%
- Rerank improves multi-session recall by +4.5%

## Usage

```python
from rolling_rag import restructure

result = restructure(
    messages=[
        {"role": "user", "content": "I'm thinking about using Rust for this..."},
        {"role": "assistant", "content": "Rust is a good choice for..."},
        # ... hundreds of messages
    ],
    llm_call=my_llm_function,  # Any LLM API (OpenAI, DeepSeek, Ollama, etc.)
)

# Result:
# result.segments    → [{name, summary, msg_span, conclusion}]
# result.relations   → [{from, to, type: "evolution|causal|contrast|..."}]
# result.global_summary → "This conversation discussed..."
# result.conclusion  → "Final decision: chose Rust because..."
```

The `llm_call` parameter is pluggable — use any model, any API, any provider.

## Why "Rolling"?

Because it doesn't stop at one level. The same mechanism that segments conversations can segment summaries, and segment the summaries of summaries. It rolls up, building higher-level structure each time.

```
Messages → Segments → Summaries → Meta-summaries → ...
```

This is how human memory works too: you don't remember every word. You remember the gist, and you can zoom in when needed.

## Project Structure

```
rolling-rag/
├── core/
│   ├── conv_indexer.py    # Core algorithm: segmentation + relations
│   ├── embedding.py       # BGE-M3 dense+sparse embedding
│   └── router.py          # LLM routing (pluggable)
├── prompts/
│   ├── conv_unified.md    # Main segmentation prompt
│   ├── registry.yaml      # Prompt registry
│   └── schemas/           # JSON schemas for structured output
├── config.py              # Configuration
└── examples/
    └── basic_usage.py     # Getting started
```

## Comparison

| | Graph RAG | MemPalace | Mem0 | **Rolling RAG** |
|---|:---:|:---:|:---:|:---:|
| Unit of memory | Entity | Fact | Fact | **Segment** |
| Structure | Entity graph | Memory palace | Vector + graph | **Relationship network** |
| Boundary detection | N/A | N/A | N/A | **Semantic (LLM)** |
| Relation types | Generic | None | Generic | **12 typed relations** |
| Multi-level | ❌ | ❌ | ❌ | **✅ Rolling abstraction** |
| Overlap continuity | ❌ | ❌ | ❌ | **✅ overlap=2** |

## License

MIT
