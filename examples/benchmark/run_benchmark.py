#!/usr/bin/env python3
"""
Traject Benchmark: Trajectory Compression — No API Key Required
===============================================================

Simulates a realistic multi-tool agent trajectory and measures actual token
reduction from Traject's compression engine.

No LLM API key needed. Token counts use tiktoken (exact).
The compression engine runs on real accumulated context.

Cost honesty
------------
Compression reduces *input* (prompt) tokens only. The model still generates
the same output, so output cost is **not** reduced. This benchmark therefore
reports:

* input-token reduction %  (what compression directly achieves),
* total-cost reduction %    (lower — it accounts for the un-compressible
  output tokens that every step still pays for), and
* compression overhead     (wall-clock ms/call — local CPU, no API $, but real
  latency that an honest evaluation must surface).

Prices are sourced from ``traject.core.pricing`` (the single source of truth)
rather than hardcoded, so they cannot drift from the SDK.

Usage:
    python examples/benchmark/run_benchmark.py
"""

import json
import statistics
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import tiktoken

try:
    import traject
    from traject.compression.engine import compress
    from traject.compression.strategies import CompressionConfig, CompressionStrategy
    from traject.core.pricing import PROVIDER_PRICING
except ImportError:
    raise SystemExit(
        "Traject SDK not found. Run from the repo root after "
        "`pip install -e sdk/python`."
    )

# ── Pricing — sourced from the SDK's authoritative table (no duplication) ──
_MODEL = "gpt-4o-mini"
_PRICING = PROVIDER_PRICING[_MODEL]
INPUT_COST_PER_TOKEN = _PRICING.input_cost_per_1m_tokens / Decimal(1_000_000)
OUTPUT_COST_PER_TOKEN = _PRICING.output_cost_per_1m_tokens / Decimal(1_000_000)

# Compression shrinks the prompt, not the completion. We model a realistic,
# fixed completion size per step so the *total* cost reflects the output tokens
# that are paid in full on every call regardless of compression.
OUTPUT_TOKENS_PER_STEP = 400

ENCODER = tiktoken.encoding_for_model(_MODEL)


def count_tokens(text: str) -> int:
    return len(ENCODER.encode(text))


def count_messages_tokens(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        total += count_tokens(m.get("content") or "")
        total += 4  # per-message overhead (role + framing)
    return total + 2  # reply priming


# ── Realistic agent trajectory ────────────────────────────────────
# Each step appends what the agent and tools would produce.
# By step 5, the context window carries 4 large tool results
# plus all prior reasoning — exactly where trajectory bloat hurts.

SYSTEM = (
    "You are a senior security engineer conducting a thorough code review. "
    "Use all available tools to analyze the codebase completely before "
    "producing your final report. Be methodical."
)

USER_TASK = (
    "Conduct a complete security review of authentication.py. "
    "Read the source, run a security scan, check test coverage, "
    "and audit the dependencies. Then produce a prioritized action plan."
)

TOOL_CALL_READ = (
    '{"tool": "read_source_file", "arguments": {"filename": "authentication.py"}}'
)

TOOL_RESULT_READ = """\
# authentication.py
import hashlib, secrets, os
from datetime import datetime, timedelta
from typing import Optional
import jwt
from database import db
from models import User

SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'fallback-insecure-key')
ALGORITHM  = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def create_access_token(data: dict, expires_delta=None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.JWTError:
        return None

def authenticate_user(username: str, password: str):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user

def get_password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

def verify_password(plain: str, hashed: str) -> bool:
    return hashed == get_password_hash(plain)
"""

TOOL_CALL_SCAN = (
    '{"tool": "run_security_scan", "arguments": {"filepath": "authentication.py"}}'
)

TOOL_RESULT_SCAN = """\
Security Scan: authentication.py
=================================
CRITICAL (1):
  Line 10: Hardcoded fallback secret key 'fallback-insecure-key'.
  JWT tokens can be forged if SECRET_KEY env var is absent.
  CWE-798: Use of Hard-coded Credentials.
  Fix: raise ValueError on startup if SECRET_KEY not set.

HIGH (2):
  Line 35: Custom SHA-256 password hashing without key stretching.
  Insufficient for password storage — brute-force risk.
  CWE-916: Insufficient Computational Effort in Password Hash.
  Fix: replace with bcrypt or Argon2.

  Line 22: Token expiry inconsistency — 15 min fallback vs 30 min constant.
  Fix: use ACCESS_TOKEN_EXPIRE_MINUTES as single source of truth.

MEDIUM (1):
  Line 29: jwt.decode does not validate 'iss' or 'aud' claims.
  Fix: pass audience= and issuer= to jwt.decode.

LOW (1):
  No rate limiting on authentication attempts.
  Fix: implement exponential backoff or account lockout.

Summary: 1 critical, 2 high, 1 medium, 1 low.
"""

TOOL_CALL_COVERAGE = (
    '{"tool": "check_test_coverage", "arguments": {"module": "authentication"}}'
)

TOOL_RESULT_COVERAGE = """\
Test Coverage Report: authentication.py
========================================
Overall coverage: 34%

create_access_token : 80%  (missing expiry edge cases)
verify_token        : 60%  (missing ExpiredSignatureError path)
authenticate_user   : 20%  (missing user-not-found, wrong-password)
get_password_hash   : 100%
verify_password     : 50%  (missing failure path)

Uncovered lines: 12, 15, 29-31, 38-40, 44-46
Uncovered branches:
  - expires_delta is None (line 22)
  - jwt.ExpiredSignatureError (line 30)
  - user not found (line 38)
  - password mismatch (line 41)

Recommendation: Coverage critically low for a security module.
Minimum target: 90%. Add tests for all failure branches.
"""

TOOL_CALL_DEPS = (
    '{"tool": "check_dependencies", "arguments": {"package": "authentication"}}'
)

TOOL_RESULT_DEPS = """\
Dependency Audit
================
PyJWT
  installed : 1.7.1
  latest    : 2.8.0
  status    : OUTDATED — SECURITY RISK
  CVE-2022-29217: Key confusion attack in versions < 2.4.0.
  Action: upgrade to >= 2.8.0 immediately.

cryptography
  installed : 3.4.8
  latest    : 42.0.5
  status    : OUTDATED
  Multiple CVEs in versions < 41.0.0.
  Action: upgrade to >= 42.0.0.

python-dotenv
  installed : 0.19.0
  latest    : 1.0.1
  status    : outdated (no known CVEs)

Recommendations:
  1. Pin PyJWT >= 2.8.0 in requirements.txt
  2. Add pip-audit to CI pipeline
  3. Enable Dependabot alerts on the repository
"""

TOOL_CALL_SCAN2 = (
    '{"tool": "run_security_scan", "arguments": {"filepath": "authentication.py",'
    ' "deep": true, "check_supply_chain": true}}'
)

TOOL_RESULT_SCAN2 = """\
Deep Security Scan Pass 2: authentication.py
=============================================
Supply chain analysis: no additional CVEs beyond pass 1.
Static analysis re-run (all findings confirmed from pass 1):

CONFIRMED CRITICAL:
  Line 10: Hardcoded fallback secret key — confirmed exploitable.
  No mitigations detected in surrounding code.

NEW FINDING — MEDIUM:
  Line 45: verify_password uses == for constant-time comparison.
  Python string == is not constant-time — timing side-channel risk.
  Fix: use hmac.compare_digest() instead of ==.

CONFIGURATION ISSUE:
  No logging of failed authentication attempts found.
  Attackers can brute-force silently. Add structured logging.

Summary: all pass-1 findings confirmed + 1 new medium + 1 config issue.
"""

TOOL_CALL_COMPLEXITY = (
    '{"tool": "check_code_complexity", "arguments": {"module": "authentication"}}'
)

TOOL_RESULT_COMPLEXITY = """\
Code Complexity Report: authentication.py
==========================================
Function                  Cyclomatic  Cognitive  LOC
──────────────────────────────────────────────────────
create_access_token            3          4       12
verify_token                   4          5       10
authenticate_user              4          4        8
get_password_hash              1          1        4
verify_password                2          2        3

Module totals: 14 functions, avg complexity 2.8, max 4.
Complexity is low — no refactoring required.

Code smell check:
  - No dead code detected.
  - Function names are clear and consistent.
  - Missing type annotations on 3 functions.
  - No docstrings on any function (add for security-critical code).

Recommendation: add type annotations and docstrings before next review.
"""

TOOL_CALL_DOCS = (
    '{"tool": "check_documentation_coverage",'
    ' "arguments": {"module": "authentication"}}'
)

TOOL_RESULT_DOCS = """\
Documentation Coverage: authentication.py
==========================================
Module docstring     : MISSING
Function docstrings  : 0 / 5 (0%)
Type annotations     : 2 / 5 (40%)

Undocumented functions:
  - create_access_token: no docstring, missing return type
  - verify_token       : no docstring, missing return type
  - authenticate_user  : no docstring, missing return type
  - get_password_hash  : no docstring (annotated)
  - verify_password    : no docstring (annotated)

Documentation is critical for security modules — reviewers and auditors
rely on docstrings to understand intended behaviour.
Recommendation: add Google-style docstrings to all 5 functions and the
module-level docstring before the next security audit.
"""

TOOL_CALL_REASONING2 = None  # not a tool call — assistant reasoning step

ASSISTANT_REASONING2 = (
    "Let me think through what the second scan and additional checks revealed. "
    "The timing side-channel in verify_password is a meaningful new finding — "
    "hmac.compare_digest is a straightforward fix. "
    "The documentation gaps don't block deployment but should be addressed "
    "alongside the type annotation work. "
    "I now have a complete picture: 6 security findings across 2 scan passes, "
    "34% test coverage, 2 critical dependency CVEs, acceptable complexity, "
    "and zero documentation. I am ready to write the final action plan."
)

ASSISTANT_REASONING = (
    "I have now gathered all the information I need. "
    "I will analyze the findings across source code, security scan, "
    "test coverage, and dependency audit to produce the final report."
)

FINAL_REPORT = """\
Security Review: authentication.py — Prioritized Action Plan
=============================================================

IMMEDIATE (fix before next deployment):
  1. Remove hardcoded fallback secret key. Raise ValueError on startup
     if JWT_SECRET_KEY env var is not set. Risk: token forgery.
  2. Upgrade PyJWT to >= 2.8.0. CVE-2022-29217 allows key confusion attacks.
  3. Replace custom SHA-256 password hashing with Argon2 or bcrypt.

SHORT-TERM (fix within current sprint):
  4. Resolve token expiry inconsistency. Use ACCESS_TOKEN_EXPIRE_MINUTES
     as the single source of truth.
  5. Upgrade cryptography to >= 42.0.0. Multiple CVEs in current version.
  6. Add audience and issuer validation to jwt.decode calls.

MEDIUM-TERM (next sprint):
  7. Increase test coverage from 34% to >= 90%. Focus on all failure
     branches: user-not-found, wrong-password, expired tokens.
  8. Implement rate limiting on authentication endpoints.
  9. Add pip-audit to CI pipeline to catch future dependency CVEs.

Overall risk assessment: HIGH. The hardcoded fallback key and weak
password hashing are production-blocking issues.
"""


def build_trajectory() -> list[list[dict]]:
    """
    Build the sequence of message arrays sent to the LLM at each step.
    Each step is the full context window at that point in the agent run.

    The segment parser increments turn_index ONLY on assistant->user transitions.
    Each tool round ends with an assistant acknowledgement so that the next
    user message triggers a new turn. With min_turns_protected=1, only the
    current turn is protected; earlier turns (with old tool results) are
    compression candidates once turns_ago > 3 (CONSERVATIVE threshold).
    """
    steps = []

    # Short acknowledgement messages that end each tool round, enabling
    # the assistant->user transition that increments turn_index.
    ACK_READ = "Source file read. Proceeding to security scan."
    ACK_SCAN = "Security scan complete. Checking test coverage next."
    ACK_COVERAGE = "Coverage checked. Running dependency audit."
    ACK_DEPS = "Dependency audit complete. Summarising so far."
    ACK_REASONING = "Summary noted. Running deep scan with supply chain check."
    ACK_SCAN2 = "Deep scan done. Checking code complexity."
    ACK_COMPLEXITY = "Complexity check done. Checking documentation coverage."
    ACK_DOCS = "Documentation coverage checked. Writing final synthesis."

    # Step 1: initial call — turn 0
    steps.append([
        {"role": "system",    "content": SYSTEM},
        {"role": "user",      "content": USER_TASK},
    ])

    # Step 2: read source, ack → turn 1 starts
    steps.append([
        {"role": "system",    "content": SYSTEM},
        {"role": "user",      "content": USER_TASK},           # turn 0
        {"role": "assistant", "content": TOOL_CALL_READ},
        {"role": "tool",      "content": TOOL_RESULT_READ},
        {"role": "assistant", "content": ACK_READ},            # triggers turn bump
        {"role": "user",      "content": "Run a security scan."},  # turn 1
    ])

    # Step 3: security scan, ack → turn 2 starts
    steps.append([
        {"role": "system",    "content": SYSTEM},
        {"role": "user",      "content": USER_TASK},
        {"role": "assistant", "content": TOOL_CALL_READ},
        {"role": "tool",      "content": TOOL_RESULT_READ},
        {"role": "assistant", "content": ACK_READ},
        {"role": "user",      "content": "Run a security scan."},
        {"role": "assistant", "content": TOOL_CALL_SCAN},
        {"role": "tool",      "content": TOOL_RESULT_SCAN},
        {"role": "assistant", "content": ACK_SCAN},
        {"role": "user",      "content": "Check test coverage."},  # turn 2
    ])

    # Step 4: coverage check, ack → turn 3 starts
    steps.append([
        {"role": "system",    "content": SYSTEM},
        {"role": "user",      "content": USER_TASK},
        {"role": "assistant", "content": TOOL_CALL_READ},
        {"role": "tool",      "content": TOOL_RESULT_READ},
        {"role": "assistant", "content": ACK_READ},
        {"role": "user",      "content": "Run a security scan."},
        {"role": "assistant", "content": TOOL_CALL_SCAN},
        {"role": "tool",      "content": TOOL_RESULT_SCAN},
        {"role": "assistant", "content": ACK_SCAN},
        {"role": "user",      "content": "Check test coverage."},
        {"role": "assistant", "content": TOOL_CALL_COVERAGE},
        {"role": "tool",      "content": TOOL_RESULT_COVERAGE},
        {"role": "assistant", "content": ACK_COVERAGE},
        {"role": "user",      "content": "Audit dependencies."},  # turn 3
    ])

    # Step 5: dependency audit, ack → turn 4 starts
    # turn 0 now has turns_ago=4 — CONSERVATIVE TOOL_RESULT threshold met.
    steps.append([
        {"role": "system",    "content": SYSTEM},
        {"role": "user",      "content": USER_TASK},
        {"role": "assistant", "content": TOOL_CALL_READ},
        {"role": "tool",      "content": TOOL_RESULT_READ},
        {"role": "assistant", "content": ACK_READ},
        {"role": "user",      "content": "Run a security scan."},
        {"role": "assistant", "content": TOOL_CALL_SCAN},
        {"role": "tool",      "content": TOOL_RESULT_SCAN},
        {"role": "assistant", "content": ACK_SCAN},
        {"role": "user",      "content": "Check test coverage."},
        {"role": "assistant", "content": TOOL_CALL_COVERAGE},
        {"role": "tool",      "content": TOOL_RESULT_COVERAGE},
        {"role": "assistant", "content": ACK_COVERAGE},
        {"role": "user",      "content": "Audit dependencies."},
        {"role": "assistant", "content": TOOL_CALL_DEPS},
        {"role": "tool",      "content": TOOL_RESULT_DEPS},
        {"role": "assistant", "content": ACK_DEPS},
        {"role": "user",      "content": "Summarise findings so far."},  # turn 4
    ])

    # Step 6: reasoning, ack → turn 5 starts
    steps.append([
        {"role": "system",    "content": SYSTEM},
        {"role": "user",      "content": USER_TASK},
        {"role": "assistant", "content": TOOL_CALL_READ},
        {"role": "tool",      "content": TOOL_RESULT_READ},
        {"role": "assistant", "content": ACK_READ},
        {"role": "user",      "content": "Run a security scan."},
        {"role": "assistant", "content": TOOL_CALL_SCAN},
        {"role": "tool",      "content": TOOL_RESULT_SCAN},
        {"role": "assistant", "content": ACK_SCAN},
        {"role": "user",      "content": "Check test coverage."},
        {"role": "assistant", "content": TOOL_CALL_COVERAGE},
        {"role": "tool",      "content": TOOL_RESULT_COVERAGE},
        {"role": "assistant", "content": ACK_COVERAGE},
        {"role": "user",      "content": "Audit dependencies."},
        {"role": "assistant", "content": TOOL_CALL_DEPS},
        {"role": "tool",      "content": TOOL_RESULT_DEPS},
        {"role": "assistant", "content": ACK_DEPS},
        {"role": "user",      "content": "Summarise findings so far."},
        {"role": "assistant", "content": ASSISTANT_REASONING},
        {"role": "assistant", "content": ACK_REASONING},
        {"role": "user",      "content": "Run deep scan with supply chain analysis."},  # turn 5
    ])

    # Step 7: second security scan, ack → turn 6 starts
    steps.append([
        {"role": "system",    "content": SYSTEM},
        {"role": "user",      "content": USER_TASK},
        {"role": "assistant", "content": TOOL_CALL_READ},
        {"role": "tool",      "content": TOOL_RESULT_READ},
        {"role": "assistant", "content": ACK_READ},
        {"role": "user",      "content": "Run a security scan."},
        {"role": "assistant", "content": TOOL_CALL_SCAN},
        {"role": "tool",      "content": TOOL_RESULT_SCAN},
        {"role": "assistant", "content": ACK_SCAN},
        {"role": "user",      "content": "Check test coverage."},
        {"role": "assistant", "content": TOOL_CALL_COVERAGE},
        {"role": "tool",      "content": TOOL_RESULT_COVERAGE},
        {"role": "assistant", "content": ACK_COVERAGE},
        {"role": "user",      "content": "Audit dependencies."},
        {"role": "assistant", "content": TOOL_CALL_DEPS},
        {"role": "tool",      "content": TOOL_RESULT_DEPS},
        {"role": "assistant", "content": ACK_DEPS},
        {"role": "user",      "content": "Summarise findings so far."},
        {"role": "assistant", "content": ASSISTANT_REASONING},
        {"role": "assistant", "content": ACK_REASONING},
        {"role": "user",      "content": "Run deep scan with supply chain analysis."},
        {"role": "assistant", "content": TOOL_CALL_SCAN2},
        {"role": "tool",      "content": TOOL_RESULT_SCAN2},
        {"role": "assistant", "content": ACK_SCAN2},
        {"role": "user",      "content": "Check code complexity."},  # turn 6
    ])

    # Step 8: complexity check, ack → turn 7 starts
    steps.append([
        {"role": "system",    "content": SYSTEM},
        {"role": "user",      "content": USER_TASK},
        {"role": "assistant", "content": TOOL_CALL_READ},
        {"role": "tool",      "content": TOOL_RESULT_READ},
        {"role": "assistant", "content": ACK_READ},
        {"role": "user",      "content": "Run a security scan."},
        {"role": "assistant", "content": TOOL_CALL_SCAN},
        {"role": "tool",      "content": TOOL_RESULT_SCAN},
        {"role": "assistant", "content": ACK_SCAN},
        {"role": "user",      "content": "Check test coverage."},
        {"role": "assistant", "content": TOOL_CALL_COVERAGE},
        {"role": "tool",      "content": TOOL_RESULT_COVERAGE},
        {"role": "assistant", "content": ACK_COVERAGE},
        {"role": "user",      "content": "Audit dependencies."},
        {"role": "assistant", "content": TOOL_CALL_DEPS},
        {"role": "tool",      "content": TOOL_RESULT_DEPS},
        {"role": "assistant", "content": ACK_DEPS},
        {"role": "user",      "content": "Summarise findings so far."},
        {"role": "assistant", "content": ASSISTANT_REASONING},
        {"role": "assistant", "content": ACK_REASONING},
        {"role": "user",      "content": "Run deep scan with supply chain analysis."},
        {"role": "assistant", "content": TOOL_CALL_SCAN2},
        {"role": "tool",      "content": TOOL_RESULT_SCAN2},
        {"role": "assistant", "content": ACK_SCAN2},
        {"role": "user",      "content": "Check code complexity."},
        {"role": "assistant", "content": TOOL_CALL_COMPLEXITY},
        {"role": "tool",      "content": TOOL_RESULT_COMPLEXITY},
        {"role": "assistant", "content": ACK_COMPLEXITY},
        {"role": "user",      "content": "Check documentation coverage."},  # turn 7
    ])

    # Step 9: documentation check, ack → turn 8 starts
    steps.append([
        {"role": "system",    "content": SYSTEM},
        {"role": "user",      "content": USER_TASK},
        {"role": "assistant", "content": TOOL_CALL_READ},
        {"role": "tool",      "content": TOOL_RESULT_READ},
        {"role": "assistant", "content": ACK_READ},
        {"role": "user",      "content": "Run a security scan."},
        {"role": "assistant", "content": TOOL_CALL_SCAN},
        {"role": "tool",      "content": TOOL_RESULT_SCAN},
        {"role": "assistant", "content": ACK_SCAN},
        {"role": "user",      "content": "Check test coverage."},
        {"role": "assistant", "content": TOOL_CALL_COVERAGE},
        {"role": "tool",      "content": TOOL_RESULT_COVERAGE},
        {"role": "assistant", "content": ACK_COVERAGE},
        {"role": "user",      "content": "Audit dependencies."},
        {"role": "assistant", "content": TOOL_CALL_DEPS},
        {"role": "tool",      "content": TOOL_RESULT_DEPS},
        {"role": "assistant", "content": ACK_DEPS},
        {"role": "user",      "content": "Summarise findings so far."},
        {"role": "assistant", "content": ASSISTANT_REASONING},
        {"role": "assistant", "content": ACK_REASONING},
        {"role": "user",      "content": "Run deep scan with supply chain analysis."},
        {"role": "assistant", "content": TOOL_CALL_SCAN2},
        {"role": "tool",      "content": TOOL_RESULT_SCAN2},
        {"role": "assistant", "content": ACK_SCAN2},
        {"role": "user",      "content": "Check code complexity."},
        {"role": "assistant", "content": TOOL_CALL_COMPLEXITY},
        {"role": "tool",      "content": TOOL_RESULT_COMPLEXITY},
        {"role": "assistant", "content": ACK_COMPLEXITY},
        {"role": "user",      "content": "Check documentation coverage."},
        {"role": "assistant", "content": TOOL_CALL_DOCS},
        {"role": "tool",      "content": TOOL_RESULT_DOCS},
        {"role": "assistant", "content": ACK_DOCS},
        {"role": "user",      "content": "Write the final action plan."},  # turn 8
    ])

    # Step 10: final report — turn 8 (current/protected).
    # Turns 0-4 have turns_ago >= 4 so CONSERVATIVE TOOL_RESULT SUMMARIZE fires.
    steps.append([
        {"role": "system",    "content": SYSTEM},
        {"role": "user",      "content": USER_TASK},
        {"role": "assistant", "content": TOOL_CALL_READ},
        {"role": "tool",      "content": TOOL_RESULT_READ},
        {"role": "assistant", "content": ACK_READ},
        {"role": "user",      "content": "Run a security scan."},
        {"role": "assistant", "content": TOOL_CALL_SCAN},
        {"role": "tool",      "content": TOOL_RESULT_SCAN},
        {"role": "assistant", "content": ACK_SCAN},
        {"role": "user",      "content": "Check test coverage."},
        {"role": "assistant", "content": TOOL_CALL_COVERAGE},
        {"role": "tool",      "content": TOOL_RESULT_COVERAGE},
        {"role": "assistant", "content": ACK_COVERAGE},
        {"role": "user",      "content": "Audit dependencies."},
        {"role": "assistant", "content": TOOL_CALL_DEPS},
        {"role": "tool",      "content": TOOL_RESULT_DEPS},
        {"role": "assistant", "content": ACK_DEPS},
        {"role": "user",      "content": "Summarise findings so far."},
        {"role": "assistant", "content": ASSISTANT_REASONING},
        {"role": "assistant", "content": ACK_REASONING},
        {"role": "user",      "content": "Run deep scan with supply chain analysis."},
        {"role": "assistant", "content": TOOL_CALL_SCAN2},
        {"role": "tool",      "content": TOOL_RESULT_SCAN2},
        {"role": "assistant", "content": ACK_SCAN2},
        {"role": "user",      "content": "Check code complexity."},
        {"role": "assistant", "content": TOOL_CALL_COMPLEXITY},
        {"role": "tool",      "content": TOOL_RESULT_COMPLEXITY},
        {"role": "assistant", "content": ACK_COMPLEXITY},
        {"role": "user",      "content": "Check documentation coverage."},
        {"role": "assistant", "content": TOOL_CALL_DOCS},
        {"role": "tool",      "content": TOOL_RESULT_DOCS},
        {"role": "assistant", "content": ACK_DOCS},
        {"role": "user",      "content": "Write the final action plan."},
        {"role": "assistant", "content": ASSISTANT_REASONING2},
        {"role": "assistant", "content": FINAL_REPORT},
    ])

    return steps
@dataclass
class StepResult:
    step: int
    baseline_tokens: int
    compressed_tokens: int
    compress_ms: float = 0.0

    @property
    def tokens_saved(self) -> int:
        return self.baseline_tokens - self.compressed_tokens

    @property
    def compression_ratio(self) -> float:
        if self.baseline_tokens == 0:
            return 0.0
        return self.tokens_saved / self.baseline_tokens


def run_benchmark(
    n_iterations: int = 10,
    strategy: CompressionStrategy = CompressionStrategy.CONSERVATIVE,
) -> tuple[list[StepResult], dict]:

    config = CompressionConfig(
        strategy=strategy,
        target_reduction_pct=0.20,
        min_turns_protected=1,
        protect_system_prompt=True,
        shadow_mode=False,
    )

    # Task hint enables semantic scoring — without it, all segments score ~0.64
    # (semantic defaults to 1.0) and no compression fires. The hint tells the
    # relevance scorer what the *current* task is so it can deprioritise old
    # tool results that are no longer relevant.
    task_hint = (
        "Write the final security action plan based on all collected findings."
    )

    trajectory = build_trajectory()
    all_step_results: list[list[StepResult]] = []

    print(f"\n{'─'*62}")
    print(f"  Running {n_iterations} iterations × {len(trajectory)} steps each")
    print(f"  Strategy: {strategy.value.upper()}  |  Model: gpt-4o-mini (projected)")
    print(f"{'─'*62}")

    for iteration in range(n_iterations):
        iteration_steps: list[StepResult] = []

        for step_idx, messages in enumerate(trajectory):
            baseline_tokens = count_messages_tokens(messages)

            t0 = time.perf_counter()
            result = compress(messages, config=config, task_hint=task_hint)
            compress_ms = (time.perf_counter() - t0) * 1000.0
            compressed_tokens = count_messages_tokens(result.messages)

            iteration_steps.append(StepResult(
                step=step_idx + 1,
                baseline_tokens=baseline_tokens,
                compressed_tokens=compressed_tokens,
                compress_ms=compress_ms,
            ))

        all_step_results.append(iteration_steps)

        total_baseline   = sum(s.baseline_tokens   for s in iteration_steps)
        total_compressed = sum(s.compressed_tokens for s in iteration_steps)
        saved = total_baseline - total_compressed
        pct   = saved / total_baseline * 100 if total_baseline else 0
        print(f"  iter {iteration+1:>2}/{n_iterations}  "
              f"baseline={total_baseline:,}  "
              f"compressed={total_compressed:,}  "
              f"saved={saved:,} ({pct:.1f}%)")

    # Aggregate across iterations
    def per_iter_total(key: str) -> list[int]:
        return [
            sum(getattr(s, key) for s in itr)
            for itr in all_step_results
        ]

    baseline_totals   = per_iter_total("baseline_tokens")
    compressed_totals = per_iter_total("compressed_tokens")
    savings_totals    = [b - c for b, c in zip(baseline_totals, compressed_totals)]

    avg_baseline   = statistics.mean(baseline_totals)
    avg_compressed = statistics.mean(compressed_totals)
    avg_saved      = statistics.mean(savings_totals)
    avg_pct        = avg_saved / avg_baseline * 100 if avg_baseline else 0

    in_cost = float(INPUT_COST_PER_TOKEN)
    out_cost = float(OUTPUT_COST_PER_TOKEN)

    # Output tokens are generated fresh every step and are NOT reduced by
    # compression — they are paid in full in both the baseline and compressed
    # runs. Including them is what separates honest *total cost* reduction from
    # the (larger) input-token reduction.
    output_tokens_per_run = OUTPUT_TOKENS_PER_STEP * len(trajectory)
    output_cost_per_run = output_tokens_per_run * out_cost

    avg_baseline_input_cost   = avg_baseline   * in_cost
    avg_compressed_input_cost = avg_compressed * in_cost
    avg_baseline_total_cost   = avg_baseline_input_cost   + output_cost_per_run
    avg_compressed_total_cost = avg_compressed_input_cost + output_cost_per_run

    input_cost_pct = (
        (avg_baseline_input_cost - avg_compressed_input_cost)
        / avg_baseline_input_cost * 100
        if avg_baseline_input_cost else 0
    )
    total_cost_pct = (
        (avg_baseline_total_cost - avg_compressed_total_cost)
        / avg_baseline_total_cost * 100
        if avg_baseline_total_cost else 0
    )

    all_steps = [s for itr in all_step_results for s in itr]
    avg_compress_ms = statistics.mean(s.compress_ms for s in all_steps) if all_steps else 0.0

    summary = {
        "date": str(date.today()),
        "strategy": strategy.value,
        "model_projected": _MODEL,
        "pricing_last_verified": str(_PRICING.last_verified),
        "iterations": n_iterations,
        "steps_per_run": len(trajectory),
        "output_tokens_per_step_modeled": OUTPUT_TOKENS_PER_STEP,
        "baseline": {
            "avg_input_tokens": round(avg_baseline),
            "avg_input_cost_usd": round(avg_baseline_input_cost, 8),
            "avg_total_cost_usd": round(avg_baseline_total_cost, 8),
        },
        "with_traject": {
            "avg_input_tokens": round(avg_compressed),
            "avg_input_cost_usd": round(avg_compressed_input_cost, 8),
            "avg_total_cost_usd": round(avg_compressed_total_cost, 8),
        },
        "reduction": {
            "avg_tokens_saved": round(avg_saved),
            "input_tokens_pct": round(avg_pct, 1),
            "input_cost_pct": round(input_cost_pct, 1),
            "total_cost_pct": round(total_cost_pct, 1),
        },
        "overhead": {
            "avg_compress_ms_per_call": round(avg_compress_ms, 2),
            "note": "local CPU (embedding) — no API cost, but real added latency",
        },
    }

    return all_steps, summary


def print_summary(summary: dict) -> None:
    b = summary["baseline"]
    a = summary["with_traject"]
    r = summary["reduction"]
    o = summary["overhead"]

    print(f"\n{'═'*64}")
    print(f"  RESULTS  ({summary['iterations']} iterations × "
          f"{summary['steps_per_run']} steps)")
    print(f"{'═'*64}")
    print(f"  {'Metric':<34} {'Baseline':>12} {'Traject':>12}")
    print(f"  {'─'*34} {'─'*12} {'─'*12}")
    print(f"  {'Avg input tokens / run':<34} "
          f"{b['avg_input_tokens']:>12,} {a['avg_input_tokens']:>12,}")
    print(f"  {'Avg input cost / run (USD)':<34} "
          f"${b['avg_input_cost_usd']:>11.6f} ${a['avg_input_cost_usd']:>11.6f}")
    print(f"  {'Avg TOTAL cost / run (USD)':<34} "
          f"${b['avg_total_cost_usd']:>11.6f} ${a['avg_total_cost_usd']:>11.6f}")
    print(f"  {'(incl. un-compressible output)':<34}")
    print(f"  {'─'*34} {'─'*12} {'─'*12}")
    print(f"  {'Tokens saved / run':<34} {'—':>12} {r['avg_tokens_saved']:>+12,}")
    print(f"  {'Input token reduction':<34} {'—':>12} {r['input_tokens_pct']:>11.1f}%")
    print(f"  {'TOTAL cost reduction':<34} {'—':>12} {r['total_cost_pct']:>11.1f}%")
    print(f"{'═'*64}")
    print(f"  Compression overhead: {o['avg_compress_ms_per_call']:.1f} ms/call "
          f"({o['note']})")
    print(f"  Pricing: {summary['model_projected']} "
          f"(last verified {summary['pricing_last_verified']}), "
          f"{summary['output_tokens_per_step_modeled']} output tokens/step modeled")


def print_readme_block(summary: dict) -> None:
    b = summary["baseline"]
    a = summary["with_traject"]
    r = summary["reduction"]
    o = summary["overhead"]

    block = f"""
## Benchmark

> **Workload:** 10-step code review agent (read source → security scan →
> test coverage → dependency audit → reasoning → second security pass →
> complexity check → documentation check → synthesis → final report)
> **Token counting:** tiktoken (exact); cost at {summary["model_projected"]} pricing
> (last verified {summary["pricing_last_verified"]}),
> modeling {summary["output_tokens_per_step_modeled"]} output tokens/step
> **Compression strategy:** {summary["strategy"].upper()}
> **Iterations:** {summary["iterations"]}

| Metric | Without Traject | With Traject | Reduction |
|--------|-----------------|--------------|-----------|
| Input tokens per run | {b["avg_input_tokens"]:,} | {a["avg_input_tokens"]:,} | **{r["input_tokens_pct"]}%** |
| Input cost per run | ${b["avg_input_cost_usd"]:.6f} | ${a["avg_input_cost_usd"]:.6f} | **{r["input_cost_pct"]}%** |
| **Total** cost per run (incl. output) | ${b["avg_total_cost_usd"]:.6f} | ${a["avg_total_cost_usd"]:.6f} | **{r["total_cost_pct"]}%** |
| Tokens saved per run | — | {r["avg_tokens_saved"]:,} | — |
| Compression overhead | — | {o["avg_compress_ms_per_call"]:.1f} ms/call | — |

In a multi-step agent, each LLM call re-pays for all prior tool results and
reasoning in the context window. Traject's compression engine identifies stale
tool outputs and completed reasoning blocks and compresses them before each
call, cutting **input** token spend by **{r["input_tokens_pct"]}%** on this
workload. Because the model still produces the same output (which compression
cannot shrink), the **total** cost reduction is **{r["total_cost_pct"]}%** —
the honest figure to plan against.

_Reproduced with `python examples/benchmark/run_benchmark.py` — no API key required._
"""

    print(f"\n{'─'*62}")
    print("  README BLOCK — paste into README.md")
    print(f"{'─'*62}")
    print(block)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Traject compression benchmark")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--strategy", choices=["conservative", "moderate", "aggressive"],
                        default="conservative")
    parser.add_argument("--output", type=str, default="benchmark_results.json")
    args = parser.parse_args()

    strategy_map = {
        "conservative": CompressionStrategy.CONSERVATIVE,
        "moderate":     CompressionStrategy.MODERATE,
        "aggressive":   CompressionStrategy.AGGRESSIVE,
    }

    t0 = time.perf_counter()
    _, summary = run_benchmark(
        n_iterations=args.iterations,
        strategy=strategy_map[args.strategy],
    )
    elapsed = time.perf_counter() - t0

    print_summary(summary)
    print_readme_block(summary)

    with open(args.output, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"  Results saved to {args.output}")
    print(f"  Total runtime: {elapsed:.1f}s")