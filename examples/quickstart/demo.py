#!/usr/bin/env python3
"""
Axon Quickstart — No API Key Required
======================================

This demo instruments a simulated 6-step agent trajectory, runs Axon's
compression engine in shadow mode, and shows exactly what would be saved
on a real LLM workload.

Run:
    cd sdk/python && source .venv/bin/activate
    python ../../examples/quickstart/demo.py
"""

import sys
import time
from decimal import Decimal

# ── Dependency check ────────────────────────────────────────────────────────
try:
    import axon
    from axon.compression.engine import compress
    from axon.compression.strategies import (
        CompressionConfig,
        CompressionStrategy,
    )
    from axon.core.cost_calculator import calculate_cost
except ImportError:
    sys.exit(
        "axon-sdk not found.\n"
        "Run: pip install axon-sdk\n"
        "Or from the repo: pip install -e sdk/python"
    )

try:
    import tiktoken
    ENCODER = tiktoken.encoding_for_model("gpt-4o-mini")
    def token_count(text: str) -> int:
        return len(ENCODER.encode(text))
except ImportError:
    # Rough approximation if tiktoken not installed
    def token_count(text: str) -> int:
        return len(text.split()) * 4 // 3


# ── Simulated agent context (realistic tool results) ─────────────────────────

SYSTEM = (
    "You are a senior security engineer. Use all available tools "
    "to analyze the codebase, then produce a prioritized report."
)

MESSAGES = [
    {"role": "system", "content": SYSTEM},
    {"role": "user",   "content": "Review authentication.py for security issues."},
    # Tool call 1: read source file
    {"role": "assistant", "content": '{"tool": "read_file", "args": {"path": "authentication.py"}}'},
    {"role": "tool", "content": (
        "# authentication.py\n"
        "SECRET_KEY = os.environ.get('JWT_SECRET', 'fallback-insecure-key')\n"
        "def create_token(data):\n"
        "    return jwt.encode(data, SECRET_KEY, algorithm='HS256')\n"
        "def verify_token(token):\n"
        "    try: return jwt.decode(token, SECRET_KEY, algorithms=['HS256'])\n"
        "    except jwt.ExpiredSignatureError: return None\n"
        "    except jwt.JWTError: return None\n"
        "def get_password_hash(password):\n"
        "    salt = secrets.token_hex(16)\n"
        "    return hashlib.sha256(f'{salt}{password}'.encode()).hexdigest()\n"
    )},
    # Tool call 2: security scan
    {"role": "assistant", "content": '{"tool": "security_scan", "args": {"path": "authentication.py"}}'},
    {"role": "tool", "content": (
        "CRITICAL: Hardcoded fallback secret 'fallback-insecure-key' (line 1). "
        "JWT tokens can be forged. CWE-798.\n"
        "HIGH: Custom SHA-256 without key stretching. Use bcrypt/Argon2. CWE-916.\n"
        "MEDIUM: No audience/issuer validation in jwt.decode.\n"
        "LOW: No rate limiting on authentication attempts.\n"
        "Summary: 1 critical, 1 high, 1 medium, 1 low."
    )},
    # Tool call 3: test coverage
    {"role": "assistant", "content": '{"tool": "coverage_check", "args": {"module": "authentication"}}'},
    {"role": "tool", "content": (
        "Overall coverage: 34%. "
        "create_token: 80%, verify_token: 60% (missing ExpiredSignatureError), "
        "get_password_hash: 100%, authenticate_user: 20%. "
        "Uncovered: lines 12, 15, 29-31, 38-40. "
        "Recommendation: increase to 90% minimum for security modules."
    )},
    # Tool call 4: dependency audit
    {"role": "assistant", "content": '{"tool": "dep_audit", "args": {}}'},
    {"role": "tool", "content": (
        "PyJWT 1.7.1 → OUTDATED. CVE-2022-29217 (key confusion attack). "
        "Upgrade to >= 2.8.0 immediately.\n"
        "cryptography 3.4.8 → OUTDATED. Multiple CVEs < 41.0.0. "
        "Upgrade to >= 42.0.0.\n"
        "Action: pin upgraded versions in requirements.txt, "
        "add pip-audit to CI pipeline."
    )},
    # Reasoning step
    {"role": "assistant", "content": (
        "I have gathered all necessary information. "
        "I will now synthesize the findings into a prioritized action plan."
    )},
]

INPUT_COST_PER_TOKEN = Decimal("0.00000015")  # gpt-4o-mini


def count_messages_tokens(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        total += token_count(m.get("content") or "")
        total += 4
    return total + 2


def print_span_header() -> None:
    print()
    print("━" * 58)
    print("  Axon SDK — Shadow Mode Demo")
    print("  Compression engine running on simulated agent trajectory")
    print("━" * 58)


def print_span(
    step: int,
    baseline_tokens: int,
    compressed_tokens: int,
    tokens_saved: int,
    cost_baseline: Decimal,
    cost_compressed: Decimal,
) -> None:
    pct = tokens_saved / baseline_tokens * 100 if baseline_tokens else 0
    status = "SHADOW" if tokens_saved > 0 else "PROTECTED"
    print(
        f"\n  Step {step}  [{status}]\n"
        f"    input_tokens (baseline)   : {baseline_tokens:>6,}\n"
        f"    input_tokens (compressed) : {compressed_tokens:>6,}  "
        f"{'↓ ' + str(tokens_saved) + ' tokens saved' if tokens_saved else '(nothing to compress yet)'}\n"
        f"    compression_ratio         : {pct:>5.1f}%\n"
        f"    projected_cost            : ${cost_baseline:.6f} → "
        f"${cost_compressed:.6f}  "
        f"(saves ${float(cost_baseline - cost_compressed):.6f})"
    )


def main() -> None:
    print_span_header()

    print("\n  Configuring Axon (shadow_mode=True, CONSERVATIVE strategy)...")
    axon.configure(export_to_stdout=False)

    config = CompressionConfig(
        strategy=CompressionStrategy.CONSERVATIVE,
        target_reduction_pct=0.20,
        min_turns_protected=1,
        protect_system_prompt=True,
        shadow_mode=True,
    )

    print("  Running 6-step agent trajectory...\n")
    time.sleep(0.3)  # let model load quietly

    total_baseline = 0
    total_compressed = 0

    # Simulate the context window growing at each agent step
    steps = [
        MESSAGES[:2],   # step 1: system + user task
        MESSAGES[:4],   # step 2: + tool call 1 + result
        MESSAGES[:6],   # step 3: + tool call 2 + result
        MESSAGES[:8],   # step 4: + tool call 3 + result
        MESSAGES[:10],  # step 5: + tool call 4 + result
        MESSAGES[:11],  # step 6: + reasoning block
    ]

    for i, context in enumerate(steps, 1):
        baseline_tokens = count_messages_tokens(context)
        result = compress(context, config=config)
        compressed_tokens = count_messages_tokens(result.messages)
        tokens_saved = baseline_tokens - compressed_tokens

        cost_b = Decimal(baseline_tokens) * INPUT_COST_PER_TOKEN
        cost_c = Decimal(compressed_tokens) * INPUT_COST_PER_TOKEN

        total_baseline += baseline_tokens
        total_compressed += compressed_tokens

        print_span(i, baseline_tokens, compressed_tokens,
                   tokens_saved, cost_b, cost_c)

    total_saved = total_baseline - total_compressed
    total_pct = total_saved / total_baseline * 100 if total_baseline else 0
    total_cost_b = Decimal(total_baseline) * INPUT_COST_PER_TOKEN
    total_cost_c = Decimal(total_compressed) * INPUT_COST_PER_TOKEN
    total_cost_saved = total_cost_b - total_cost_c

    print()
    print("━" * 58)
    print("  SUMMARY (shadow mode — no context was modified)")
    print("━" * 58)
    print(f"  Total input tokens (baseline)   : {total_baseline:,}")
    print(f"  Total input tokens (compressed) : {total_compressed:,}")
    print(f"  Tokens that would be saved      : {total_saved:,} ({total_pct:.1f}%)")
    print(f"  Projected cost (baseline)       : ${float(total_cost_b):.6f}")
    print(f"  Projected cost (compressed)     : ${float(total_cost_c):.6f}")
    print(f"  Cost saved per agent run        : ${float(total_cost_saved):.6f}")
    print()
    print("  Shadow mode: compression was computed but NOT applied.")
    print("  Set shadow_mode=False to enable live compression.")
    print()
    print("  Next steps:")
    print("  1. Instrument your own agent:")
    print("     axon.patch(client, feature_tag='my_agent', shadow_mode=True)")
    print("  2. Validate savings with: axon analyze --input spans.jsonl")
    print("  3. Enable live compression when satisfied:")
    print("     axon.patch(client, shadow_mode=False)")
    print()


if __name__ == "__main__":
    main()
