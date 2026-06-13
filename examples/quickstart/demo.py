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
        "# authentication.py  (248 lines)\n"
        "import os, jwt, hashlib, secrets\n"
        "from datetime import datetime, timedelta\n"
        "from typing import Optional\n\n"
        "SECRET_KEY = os.environ.get('JWT_SECRET', 'fallback-insecure-key')\n"
        "ALGORITHM = 'HS256'\n"
        "ACCESS_TOKEN_EXPIRE_MINUTES = 30\n\n"
        "def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):\n"
        "    to_encode = data.copy()\n"
        "    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))\n"
        "    to_encode.update({'exp': expire})\n"
        "    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)\n\n"
        "def verify_token(token: str):\n"
        "    try:\n"
        "        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])\n"
        "        username = payload.get('sub')\n"
        "        if username is None:\n"
        "            return None\n"
        "        return payload\n"
        "    except jwt.ExpiredSignatureError:\n"
        "        return None\n"
        "    except jwt.JWTError:\n"
        "        return None\n\n"
        "def get_password_hash(password: str) -> str:\n"
        "    salt = secrets.token_hex(16)\n"
        "    return hashlib.sha256(f'{salt}{password}'.encode()).hexdigest()\n\n"
        "def authenticate_user(db, username: str, password: str):\n"
        "    user = db.query(User).filter(User.username == username).first()\n"
        "    if not user or not verify_password(password, user.hashed_password):\n"
        "        return False\n"
        "    return user\n"
    )},
    # Tool call 2: security scan
    {"role": "assistant", "content": '{"tool": "security_scan", "args": {"path": "authentication.py"}}'},
    {"role": "tool", "content": (
        "Semgrep security scan results for authentication.py:\n\n"
        "CRITICAL [CWE-798] — Hardcoded fallback secret detected (line 6).\n"
        "  Rule: python.lang.security.hardcoded-jwt-secret\n"
        "  Detail: SECRET_KEY falls back to the literal string 'fallback-insecure-key' when\n"
        "  JWT_SECRET env var is unset. An attacker who knows this value can forge arbitrary\n"
        "  JWT tokens and bypass all authentication. Rotate immediately if this has reached\n"
        "  any non-local environment. Fix: raise RuntimeError if JWT_SECRET is unset.\n\n"
        "HIGH [CWE-916] — Weak password hashing (line 27).\n"
        "  Rule: python.lang.security.weak-password-hash\n"
        "  Detail: get_password_hash uses raw SHA-256 with a custom salt. SHA-256 is a\n"
        "  general-purpose hash — it is not designed for passwords and can be brute-forced\n"
        "  at billions of guesses per second on commodity hardware. Replace with bcrypt\n"
        "  (cost factor >= 12) or Argon2id from the argon2-cffi package.\n\n"
        "MEDIUM [CWE-345] — Missing audience and issuer validation (line 15).\n"
        "  Detail: jwt.decode does not validate 'aud' or 'iss' claims. A token issued for\n"
        "  a different service could be accepted. Add options={'require': ['aud', 'iss']}.\n\n"
        "LOW — No rate limiting on authentication endpoint (line 33).\n"
        "  Detail: authenticate_user is called directly with no throttling. Add\n"
        "  slowapi or equivalent to limit to 5 attempts per minute per IP.\n\n"
        "Summary: 1 CRITICAL, 1 HIGH, 1 MEDIUM, 1 LOW. Recommend blocking PR until\n"
        "CRITICAL and HIGH findings are resolved.\n"
    )},
    # Tool call 3: test coverage
    {"role": "assistant", "content": '{"tool": "coverage_check", "args": {"module": "authentication"}}'},
    {"role": "tool", "content": (
        "Coverage report — authentication.py\n"
        "Generated: 2024-11-01 09:14:02 UTC\n\n"
        "Name                    Stmts   Miss  Cover   Missing lines\n"
        "-------------------------------------------------------------\n"
        "authentication.py          48     31    34%   12, 15, 18-22,\n"
        "                                             29-31, 33-40,\n"
        "                                             44-48, 52-61\n\n"
        "Function-level breakdown:\n"
        "  create_access_token   : 80%  — missing expiry edge case (line 12)\n"
        "  verify_token          : 60%  — ExpiredSignatureError path untested (line 18)\n"
        "                                  JWTError path untested (line 21)\n"
        "                                  None username path untested (line 15)\n"
        "  get_password_hash     : 100% — fully covered\n"
        "  authenticate_user     : 20%  — only happy path tested; wrong-password,\n"
        "                                  unknown-user, and DB-error paths all missing\n\n"
        "Branch coverage: 28% (14/50 branches hit)\n\n"
        "Recommendation: Security-critical modules should have >= 90% statement coverage\n"
        "and >= 85% branch coverage before merging. Current state is far below threshold.\n"
        "Priority: add tests for all failure paths in verify_token and authenticate_user.\n"
    )},
    # Tool call 4: dependency audit
    {"role": "assistant", "content": '{"tool": "dep_audit", "args": {}}'},
    {"role": "tool", "content": (
        "pip-audit results for requirements.txt (scanned 47 packages):\n\n"
        "VULNERABLE PACKAGES:\n\n"
        "PyJWT 1.7.1  [CRITICAL]\n"
        "  CVE-2022-29217 — Key confusion / algorithm confusion attack.\n"
        "  An attacker can craft a token using an RSA public key as an HMAC secret,\n"
        "  causing the server to accept forged tokens without the private key.\n"
        "  CVSS score: 9.8 (Critical). Fix: upgrade to >= 2.8.0 immediately.\n"
        "  Note: v2.x also changes the decode API; update call sites accordingly.\n\n"
        "cryptography 3.4.8  [HIGH]\n"
        "  Affected by 7 CVEs in versions < 41.0.0, including:\n"
        "  CVE-2023-49083 — NULL pointer dereference in PKCS12 parsing.\n"
        "  CVE-2023-0286  — X.400 address type confusion (OpenSSL upstream).\n"
        "  CVE-2022-3602  — Buffer overflow in punycode name constraint checking.\n"
        "  Fix: upgrade to >= 42.0.0. Breaking changes: none for standard usage.\n\n"
        "passlib 1.7.4  [LOW]\n"
        "  No CVEs, but package is unmaintained (last release 2020). Consider\n"
        "  migrating to argon2-cffi for password hashing.\n\n"
        "CLEAN PACKAGES: 44 packages have no known vulnerabilities.\n\n"
        "Recommended actions:\n"
        "  1. Pin PyJWT >= 2.8.0 and cryptography >= 42.0.0 in requirements.txt.\n"
        "  2. Add pip-audit to CI pipeline (pre-commit or GitHub Actions step).\n"
        "  3. Configure Dependabot or Renovate for automated dependency updates.\n"
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
        min_turns_protected=0,
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
        # Use the engine's internal token counts — result.messages is the
        # original (unmodified) in shadow mode, so we must not re-count it.
        compressed_tokens = result.compressed_tokens
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
