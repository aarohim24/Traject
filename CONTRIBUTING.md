# Contributing to Axon

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/aarohimathur/axon.git
   cd axon
   ```

2. Create and activate a virtual environment:
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   ```

3. Install the package with all development and optional extras:
   ```bash
   pip install -e "sdk/python[dev,openai,anthropic,langchain]"
   ```

4. Run the test suite:
   ```bash
   pytest sdk/python/tests/
   ```
