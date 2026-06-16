#!/usr/bin/env bash
# setup_contributor.sh — Bootstrap a complete Traject development environment.
#
# Checks for required toolchain versions, creates a Python virtual environment,
# installs all dependencies (SDK + backend + dashboard), and wires up pre-commit
# hooks so that linting and type-checking run automatically before each commit.
#
# Usage:
#   bash community/scripts/setup_contributor.sh
#
# Requirements:
#   - Python >= 3.11
#   - Node >= 20

set -euo pipefail

# ── colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Colour

info()    { echo -e "${GREEN}[traject]${NC} $*"; }
warning() { echo -e "${YELLOW}[traject]${NC} $*"; }
error()   { echo -e "${RED}[traject ERROR]${NC} $*" >&2; }

# ── repository root ───────────────────────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
info "Repository root: $REPO_ROOT"

# ── 1. Check Python >= 3.11 ───────────────────────────────────────────────────
info "Checking Python version..."

if ! command -v python3 &>/dev/null; then
    error "python3 not found. Please install Python 3.11 or later."
    error "  macOS:   brew install python@3.11"
    error "  Ubuntu:  sudo apt install python3.11"
    exit 1
fi

PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_MAJOR="$(echo "$PYTHON_VERSION" | cut -d. -f1)"
PYTHON_MINOR="$(echo "$PYTHON_VERSION" | cut -d. -f2)"

if [[ "$PYTHON_MAJOR" -lt 3 || ( "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 11 ) ]]; then
    error "Python $PYTHON_VERSION detected. Traject requires Python 3.11 or later."
    error "  macOS:   brew install python@3.11"
    error "  Ubuntu:  sudo apt install python3.11"
    exit 1
fi
info "Python $PYTHON_VERSION ✓"

# ── 2. Check Node >= 20 ───────────────────────────────────────────────────────
info "Checking Node.js version..."

if ! command -v node &>/dev/null; then
    error "node not found. Please install Node.js 20 or later."
    error "  nvm:   nvm install 20 && nvm use 20"
    error "  brew:  brew install node@20"
    exit 1
fi

NODE_VERSION="$(node --version | sed 's/^v//')"
NODE_MAJOR="$(echo "$NODE_VERSION" | cut -d. -f1)"

if [[ "$NODE_MAJOR" -lt 20 ]]; then
    error "Node.js $NODE_VERSION detected. Traject requires Node.js 20 or later."
    error "  nvm:   nvm install 20 && nvm use 20"
    error "  brew:  brew install node@20"
    exit 1
fi
info "Node.js $NODE_VERSION ✓"

# ── 3. Create Python virtual environment ─────────────────────────────────────
info "Creating Python virtual environment at .venv/ ..."
python3 -m venv .venv
info ".venv created ✓"

# Activate for the rest of this script
# shellcheck disable=SC1091
source .venv/bin/activate
info "Virtual environment activated ✓"

# ── 4. Upgrade pip / setuptools ──────────────────────────────────────────────
info "Upgrading pip and setuptools..."
pip install --quiet --upgrade pip setuptools wheel

# ── 5. Install SDK dependencies ───────────────────────────────────────────────
info "Installing Python SDK (all extras: dev, ml, bedrock, vertex)..."
pip install --quiet -e "sdk/python[dev,ml,bedrock,vertex]"
info "SDK installed ✓"

# ── 6. Install backend dependencies ──────────────────────────────────────────
info "Installing backend dependencies..."
pip install --quiet -e "backend[dev]"
info "Backend installed ✓"

# ── 7. Install dashboard dependencies ────────────────────────────────────────
info "Installing dashboard dependencies (npm install)..."
(cd dashboard && npm install --silent)
info "Dashboard dependencies installed ✓"

# ── 8. Install pre-commit hooks ───────────────────────────────────────────────
info "Installing pre-commit hooks..."
pre-commit install
info "pre-commit hooks installed ✓"

# ── 9. Success ────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          Traject contributor environment is ready!              ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
info "Activate your virtual environment:"
echo "    source .venv/bin/activate"
echo ""
info "Useful commands:"
echo "    pytest sdk/python/tests/          # run Python SDK tests"
echo "    pytest backend/tests/             # run backend tests"
echo "    cd sdk/typescript && npm test     # run TypeScript tests"
echo "    cd dashboard && npm run dev       # start the dashboard dev server"
echo "    cd backend && uvicorn traject_backend.main:app --reload"
echo "                                      # start the backend API server"
echo "    ruff check sdk/python/traject        # lint the SDK"
echo "    mypy sdk/python/traject --strict     # type-check the SDK"
echo ""
info "Read CONTRIBUTING.md for the full contribution workflow."
