# Traject Quickstart

Runs without an API key. Shows shadow mode compression on a realistic 6-step agent trajectory.

## Run

```bash
cd sdk/python
source .venv/bin/activate
python ../../examples/quickstart/demo.py
```

## What you'll see

For each step of the agent, Traject shows:
- Input tokens in the context window (baseline)
- What compression would reduce it to (shadow mode)
- Tokens that would be saved
- Projected cost delta

Shadow mode never modifies your context — it only observes. Enable live compression with `shadow_mode=False` after validating.
