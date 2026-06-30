#!/usr/bin/env bash
# setup.sh — first-run bootstrap for the Traject backend.
#
# Generates a deploy/.env with strong random secrets so you can run
# `docker compose up` immediately without touching any passwords manually.
#
# Usage:
#   bash scripts/setup.sh          # creates deploy/.env (prompts before overwriting)
#   bash scripts/setup.sh --force  # overwrites without asking
#
# Requirements: bash 4+, openssl (ships on macOS + every Linux distro)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/deploy/.env"
ENV_EXAMPLE="$REPO_ROOT/deploy/.env.example"

# ── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; RESET='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────
rand_hex() { openssl rand -hex "$1"; }
rand_b64() { openssl rand -base64 "$1" | tr -d '\n/+=' | head -c "$1"; }

# ── Guard: don't overwrite an existing .env unless --force ────────────────────
if [[ -f "$ENV_FILE" ]] && [[ "${1:-}" != "--force" ]]; then
  echo -e "${YELLOW}Warning: $ENV_FILE already exists.${RESET}"
  echo "  Run with --force to overwrite: bash scripts/setup.sh --force"
  exit 1
fi

if [[ ! -f "$ENV_EXAMPLE" ]]; then
  echo "Error: $ENV_EXAMPLE not found — run this script from the repo root."
  exit 1
fi

# ── Generate secrets ──────────────────────────────────────────────────────────
PG_PASS=$(rand_hex 24)
REDIS_PASS=$(rand_hex 24)
API_KEY=$(rand_hex 32)
GRAFANA_PASS=$(rand_b64 20)

# ── Write .env from template, substituting CHANGE_ME placeholders ────────────
sed \
  -e "s/CHANGE_ME_STRONG_PASSWORD/$PG_PASS/g" \
  -e "s/CHANGE_ME_STRONG_PASSWORD/$PG_PASS/g" \
  -e "s/CHANGE_ME_API_KEY/$API_KEY/g" \
  -e "s/CHANGE_ME_STRONG_PASSWORD/$GRAFANA_PASS/g" \
  "$ENV_EXAMPLE" \
| awk -v pg="$PG_PASS" -v redis="$REDIS_PASS" -v api="$API_KEY" -v graf="$GRAFANA_PASS" '
  /^POSTGRES_PASSWORD=/ { print "POSTGRES_PASSWORD=" pg; next }
  /^DATABASE_URL=/ {
    sub(/CHANGE_ME_STRONG_PASSWORD/, pg)
    print; next
  }
  /^REDIS_PASSWORD=/ { print "REDIS_PASSWORD=" redis; next }
  /^REDIS_URL=/ {
    sub(/CHANGE_ME_STRONG_PASSWORD/, redis)
    print; next
  }
  /^TRAJECT_API_KEY=/ { print "TRAJECT_API_KEY=" api; next }
  /^API_KEY=/ { print "API_KEY=" api; next }
  /^GRAFANA_PASSWORD=/ { print "GRAFANA_PASSWORD=" graf; next }
  { print }
' > "$ENV_FILE"

chmod 600 "$ENV_FILE"

# ── Print summary ─────────────────────────────────────────────────────────────
echo -e "${GREEN}${BOLD}✓ $ENV_FILE created${RESET}"
echo ""
echo -e "  ${BOLD}API key (save this — it is not stored elsewhere):${RESET}"
echo "    $API_KEY"
echo ""
echo -e "  ${BOLD}Configure the SDK:${RESET}"
echo "    import traject"
echo "    traject.configure("
echo "        backend_url=\"http://localhost:8000\","
echo "        backend_api_key=\"$API_KEY\","
echo "    )"
echo ""
echo -e "  ${BOLD}Start the stack:${RESET}"
echo "    docker compose -f deploy/docker-compose.yml up -d"
echo ""
echo -e "  ${BOLD}Grafana dashboard:${RESET} http://localhost:3000  (admin / $GRAFANA_PASS)"
echo ""
echo -e "${YELLOW}Keep $ENV_FILE out of version control — it is already in .gitignore.${RESET}"
