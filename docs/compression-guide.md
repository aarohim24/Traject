# Compression Guide

## What is Trajectory Compression?

In a multi-step agentic workload the conversation history grows with every
turn. Tool results, reasoning blocks, RAG chunks, and few-shot examples
accumulate — and every token you send to the LLM is billed, even if it has
not been relevant for the last ten turns. A 20-step agent that started with
a 500-token system prompt may be sending 15,000 tokens of history by step
15, most of which the model ignores.

Axon's trajectory compression pipeline solves this by identifying low-relevance
segments in the history and either summarising them (replacing with a short
digest) or dropping them entirely before the next provider call. **Critical
context is always protected**: system prompts are never touched, the most
recent turns are always kept verbatim, and any message you pin with
`axon_preserve: True` is immutable.

The result is a shorter context with lower input-token cost and, in most
cases, no meaningful change to response quality.

---

## Shadow Mode (Default)

Shadow mode is the default configuration for every built-in strategy. When
`shadow_mode=True`, the full compression pipeline runs — segments are
classified, scored, and decided upon — but the compressed output is silently
discarded. The original, unmodified messages are always forwarded to the
provider.

**Why shadow mode is the default**

Shadow mode is a trust-building mechanism. It lets you observe exactly what
Axon *would* compress without changing a single byte of your live traffic.
You can inspect `CompressionResult` fields like `segments_dropped` and
`tokens_saved` for days or weeks before deciding whether to enable live
compression. There is no risk of degrading your agent's behaviour.

**How to interpret results in shadow mode**

- `messages` — your original, unmodified message list (always, in shadow mode)
- `compressed_tokens` — equals `original_tokens` (no tokens removed)
- `tokens_saved` — `0`
- `compression_ratio` — `0.0`
- `segments_retained / summarized / dropped` — reflects what the strategy
  *would* have done; this is the forward-looking view you use to evaluate
  whether live mode is safe

**Code example**

```python
from axon.compression.engine import compress
from axon.compression.strategies import CompressionConfig, CompressionStrategy

config = CompressionConfig(
    strategy=CompressionStrategy.MODERATE,
    target_reduction_pct=0.35,
    min_turns_protected=3,
    protect_system_prompt=True,
    shadow_mode=True,          # Default — pipeline runs, original returned
)

result = compress(messages, config, task_hint="Resolve the user's support ticket")

print(result.shadow_mode)          # True
print(result.tokens_saved)         # 0  (shadow: nothing actually removed)
print(result.segments_dropped)     # N  (what would have been dropped)
print(result.messages is messages) # True  (original list returned unchanged)
```

All three built-in strategies default to `shadow_mode=True`:

```python
from axon.compression.strategies import get_config, CompressionStrategy

config = get_config(CompressionStrategy.CONSERVATIVE)
print(config.shadow_mode)  # True
```

---

## Strategies

Axon ships three strategies. Each specifies a target token reduction and a
set of decision rules that govern which segment types are eligible for
summarisation or removal.

| Strategy | Target Reduction | Decision Rules |
|---|---|---|
| `CONSERVATIVE` | 20% | `TOOL_RESULT` older >3 turns & score < 0.30 → summarise; `REASONING_BLOCK` score < 0.40 → drop |
| `MODERATE` | 35% | `TOOL_RESULT` older >2 turns & score < 0.40 → summarise; `REASONING_BLOCK` score < 0.50 → drop; `RAG_CHUNK` score < 0.35 → drop |
| `AGGRESSIVE` | 55% | `TOOL_RESULT` older >1 turn & score < 0.50 → summarise; `REASONING_BLOCK` score < 0.60 → drop; `RAG_CHUNK` score < 0.45 → drop; `FEW_SHOT_EXAMPLE` score < 0.40 → drop |

Every segment type not listed in a strategy's decision rules is always
retained. All three strategies set `protect_system_prompt=True` and
`shadow_mode=True` by default.

---

## Protection Rules (Never Violable)

Certain segments are always preserved regardless of strategy, relevance
score, or any other factor. Protected segments receive a relevance score of
`1.0` and are never passed through the strategy decision table.

1. **All `SYSTEM_PROMPT` segments** — any message with `"role": "system"`
   is retained verbatim. This is enforced at two independent layers: the
   classifier marks every system segment as `protected=True`, and
   `_validate_compression_result` verifies that every system prompt present
   in the original appears unchanged in the compressed output.

2. **Last `min_turns_protected` user/assistant turn pairs** — the most
   recent turns are always kept in full. For `CONSERVATIVE` and `MODERATE`
   this is the last 3 turn pairs; for `AGGRESSIVE` it is the last 2.

3. **Any segment with metadata `axon_preserve: True`** — add this key to
   any message dict to pin it permanently, regardless of strategy or score:

   ```python
   {
       "role": "user",
       "content": "Always respond in formal English.",
       "axon_preserve": True,
   }
   ```

   The segment parser reads this flag and sets `protected=True`
   unconditionally. No strategy can touch it.

If validation fails — for example, a system prompt is somehow absent from
the compressed output — the pipeline falls back to the original messages and
appends a human-readable message to `CompressionResult.warnings`.

---

## Relevance Scoring

Every non-protected segment receives a composite relevance score in
`[0.0, 1.0]` before the strategy decision rules are applied. Higher scores
mean "keep this".

**Composite score formula**

```
score = 0.4 × recency + 0.4 × semantic + 0.2 × reference
```

**Recency** — exponential decay from the most recent turn:

```
recency = exp(-0.3 × (max_turn − segment.turn_index))
```

A segment in the current turn gets `recency = 1.0`. A segment from 5 turns
ago gets `exp(-0.3 × 5) ≈ 0.22`.

**Semantic** — cosine similarity between the segment's embedding and an
optional `task_hint` string. Both are encoded by the local
`all-MiniLM-L6-v2` model (384-dimensional, 22 MB, runs fully in-process —
no API calls, no prompt data leaves your machine). If no `task_hint` is
provided, the semantic component defaults to `1.0` for all segments.

**Reference** — a heuristic count of how many later segments reference this
segment's content:

```
reference = min(1.0, reference_count / 3)
```

A segment cited by three or more later segments receives the maximum
reference score of `1.0`.

All scores are clamped to `[0.0, 1.0]` after the weighted sum is computed.

---

## Interpreting `CompressionResult`

Every call to `compress()` returns a `CompressionResult`. Here is a walkthrough
of each field using a representative example from a 20-message conversation
run with the `MODERATE` strategy in shadow mode.

```python
from axon.compression.engine import compress
from axon.compression.strategies import get_config, CompressionStrategy

config = get_config(CompressionStrategy.MODERATE)  # shadow_mode=True by default

result = compress(messages, config, task_hint="Resolve the billing dispute")

# Example result fields:
result.original_tokens      # 4820  — total tokens in the input
result.compressed_tokens    # 4820  — equals original in shadow mode
result.tokens_saved         # 0     — shadow: nothing actually removed
result.compression_ratio    # 0.0   — shadow: ratio is 0.0
result.segments_analyzed    # 20    — one segment per input message
result.segments_retained    # 14    — would be kept verbatim
result.segments_summarized  # 3     — would be replaced with a short digest
result.segments_dropped     # 3     — would be removed entirely
result.shadow_mode          # True
result.strategy_applied     # "moderate"
result.messages             # original list — unmodified in shadow mode
result.warnings             # []  — empty on a clean run
```

**`tokens_saved`** always equals `original_tokens - compressed_tokens`. A
Pydantic model validator enforces this; an inconsistent value raises
`ValidationError` at construction time.

**`segments_analyzed`** always equals `segments_retained + segments_summarized
+ segments_dropped`. Also enforced by a model validator.

**`compression_ratio`** is `0.0` in shadow mode and whenever the pipeline
falls back to the original messages. In a live run a value of `0.356` means
35.6% of tokens were eliminated.

**`messages`** in shadow mode: your original list, untouched. In live mode
(`shadow_mode=False`): the compressed list, with summarised segments replaced
by `<first 100 chars of original> [summarized by Axon]` and dropped segments
absent.

**`warnings`** is an empty list on a clean run. A non-empty list means
validation failed and the pipeline fell back to the original messages — check
the message for the root cause before re-running with live mode.

---

## Enabling Live Compression

To have Axon actually shorten the messages sent to the LLM, set
`shadow_mode=False`. This is a deliberate user decision — Axon never enables
live compression automatically.

```python
import axon
from axon.compression.strategies import CompressionStrategy

@axon.instrument(
    feature_tag="my-agent",
    shadow_mode=False,                          # Live compression enabled
    strategy=CompressionStrategy.CONSERVATIVE,  # Start conservative
)
def call_llm(messages, **kwargs):
    return client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        **kwargs,
    )
```

Live compression modifies the messages the LLM actually receives. In most
cases the dropped or summarised segments are genuinely low-relevance and the
difference in output quality is negligible. However, you are responsible for
evaluating that risk for your use case.

**Recommended rollout path:**

1. Run in shadow mode for several days and review `tokens_saved`,
   `segments_dropped`, and `segments_summarized` in your span logs.
2. Switch to `CONSERVATIVE` live mode first — it targets only 20% reduction
   and applies the strictest thresholds.
3. Pin any message that must never be modified with `"axon_preserve": True`.
4. Monitor `CompressionResult.warnings` — a non-empty list signals a
   validation fallback to the original messages.
