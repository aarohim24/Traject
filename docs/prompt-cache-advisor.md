# Prompt Cache Advisor Guide

## How Provider Caching Works

Anthropic and OpenAI both support server-side prompt caching: when you send the same prefix of a system prompt repeatedly, the provider caches the KV state for that prefix and charges a dramatically reduced rate for subsequent requests. Anthropic charges approximately 10% of the normal input rate for cache reads; OpenAI charges 50%.

The catch: the cache only activates when the **exact same token sequence** is presented from the start of the prompt up to the cache boundary. Any variation — a dynamic date, a per-user variable, a session token — breaks the cache hit. The advisor identifies the longest stable prefix in your system prompts and tells you how to restructure them to maximise cache hit rates.

---

## CLI Usage

Run the advisor against a JSONL file of recorded `InferenceSpan` records:

```bash
axon cache-advisor --input spans.jsonl
axon cache-advisor --input spans.jsonl --provider openai
```

The advisor reads each span's `prompt_hash` to count unique prompts, identifies cacheable prefixes, and prints a rich table of opportunities.

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                        Prompt Cache Opportunities                             │
├──────────────┬─────────────┬────────────────┬──────────────────────────────────┤
│ Provider     │ Token Count │ Est. Savings % │ Recommendation                   │
├──────────────┼─────────────┼────────────────┼──────────────────────────────────┤
│ anthropic    │       2,341 │          72.0% │ Move stable prefix (2,069 tokens) │
│              │             │                │ before volatile suffix. Apply      │
│              │             │                │ cache_control to prefix block.     │
└──────────────┴─────────────┴────────────────┴──────────────────────────────────┘
```

---

## Report Interpretation

| Column | Meaning |
|---|---|
| Token Count | Tokens in the stable (cacheable) prefix |
| Est. Savings % | `stable_tokens / total_tokens × 0.9` — fraction of token cost that caching could save |
| Recommendation | What to move and where to apply the cache marker |

The 0.9 multiplier accounts for cache write cost (providers charge a small write fee on the first request that populates the cache). The estimate is conservative; actual savings depend on your cache hit rate.

**Volatile patterns detected:**
- `{variable}` format placeholders
- ISO dates (`YYYY-MM-DD`)
- Words `today`, `now`, `current date`
- `username`, `user`, `session`

Any line containing these patterns is treated as volatile; all lines from that point onward are excluded from the stable prefix.

---

## Anthropic `cache_control` Example

Restructure your system prompt to put stable content first, then mark the boundary with `cache_control`:

```python
import anthropic

client = anthropic.Anthropic()

# Stable prefix — high token count, never changes between requests
stable_system = """You are an expert Python code reviewer. You follow PEP 8, 
prefer readability over brevity, and always explain the reasoning behind your
suggestions. [... 2000+ tokens of stable instructions ...]"""

# Volatile suffix — changes per request
volatile_context = f"Today is {date.today()}. Reviewing PR from {username}."

response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    system=[
        {
            "type": "text",
            "text": stable_system,
            "cache_control": {"type": "ephemeral"},  # ← mark cache boundary here
        },
        {
            "type": "text",
            "text": volatile_context,
            # No cache_control — this part varies per request
        },
    ],
    messages=[{"role": "user", "content": pr_diff}],
)
```

---

## OpenAI Cached Prefix Example

OpenAI caches automatically based on prefix matching — no explicit marker is needed. Structure your prompt so the stable content always comes first:

```python
import openai

client = openai.OpenAI()

# Put ALL stable content at the start of the system prompt
# OpenAI caches the first N tokens automatically when the prefix is reused
stable_instructions = """You are an expert Python code reviewer...
[... 2000+ tokens of stable instructions ...]"""

# Append volatile content at the end — after the stable prefix
system_prompt = stable_instructions + f"\n\nToday: {date.today()}. User: {username}."

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": pr_diff},
    ],
)

# Check if cache was hit via usage stats
cached = response.usage.prompt_tokens_details.cached_tokens
print(f"Cached tokens: {cached} (saved ~50% on those tokens)")
```

The key rule for OpenAI: keep the first 1,024+ tokens of your system prompt **identical** across requests. Any change to that prefix invalidates the cache.
