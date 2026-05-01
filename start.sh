#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# start.sh — One command to start the entire Website Status Checker locally.
#
# What this script does, in order:
#   1. Checks that all required tools are installed (SAM, Docker, AWS CLI, npm)
#   2. Loads your AWS credentials from the .env file
#   3. Starts a local DynamoDB database (for caching results)
#   4. Builds the backend Lambda function
#   5. Starts the backend API server on port 3000
#   6. Installs frontend dependencies if needed
#   7. Starts the frontend dev server on port 5173
#   8. Opens the app in your browser automatically
# ─────────────────────────────────────────────────────────────────────────────

set -e  # Stop immediately if any command fails

# ─── Colors for terminal output ───────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
BOLD='\033[1m'
RESET='\033[0m'

# Resolve the directory where this script lives, regardless of where you run it from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
ENV_FILE="$SCRIPT_DIR/.env"

# ─── Helper functions ─────────────────────────────────────────────────────────
print_step()  { echo -e "\n${BLUE}${BOLD}▶ $1${RESET}"; }
print_ok()    { echo -e "  ${GREEN}✓${RESET} $1"; }
print_warn()  { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
print_error() { echo -e "  ${RED}✗${RESET} $1"; }

# Kills all background processes started by this script when you press Ctrl+C
cleanup() {
  echo -e "\n${YELLOW}Shutting down…${RESET}"
  kill "$DYNAMODB_PID" "$SAM_PID" "$VITE_PID" 2>/dev/null
  echo -e "${GREEN}All servers stopped. Goodbye.${RESET}"
  exit 0
}
trap cleanup SIGINT SIGTERM

# ─── Banner ───────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "   Website Status Checker — Local Dev Startup"
echo -e "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"

# ─── Step 1: Check prerequisites ─────────────────────────────────────────────
# Verify every required tool is installed before trying to start anything
print_step "Checking prerequisites"

MISSING=0
for tool in sam docker aws npm; do
  if command -v "$tool" &>/dev/null; then
    print_ok "$tool found ($(${tool} --version 2>&1 | head -1))"
  else
    print_error "$tool is not installed. Please install it and re-run this script."
    MISSING=1
  fi
done

if [ "$MISSING" -eq 1 ]; then
  echo -e "\n${RED}Missing required tools. Exiting.${RESET}"
  exit 1
fi

# ─── Step 2: Load environment variables from .env ────────────────────────────
# The .env file holds your AWS credentials so you never have to type them manually
print_step "Loading environment variables"

if [ -f "$ENV_FILE" ]; then
  # Export each line from .env as a real environment variable (skip comments and blank lines)
  set -o allexport
  source "$ENV_FILE"
  set +o allexport
  print_ok "Loaded credentials from .env"
else
  print_warn ".env file not found — falling back to system AWS credentials"
  print_warn "Copy .env.example to .env and fill in your keys if you see auth errors"
fi

# Apply AWS credentials to the environment so SAM and AWS CLI pick them up
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-2}"

print_ok "AWS region: ${AWS_DEFAULT_REGION}"

# ─── Step 3: Start local DynamoDB ────────────────────────────────────────────
# DynamoDB Local is a lightweight database that runs in Docker.
# It caches website check results so the same site isn't re-checked too often.
print_step "Starting local DynamoDB"

# Check if Docker is actually running (installed ≠ running)
if ! docker info &>/dev/null; then
  print_error "Docker is installed but not running. Please open Docker Desktop and try again."
  exit 1
fi

# Check if DynamoDB is already on port 8000 — don't start a second one
if lsof -i:8000 &>/dev/null; then
  print_warn "Port 8000 already in use — assuming DynamoDB is already running"
  DYNAMODB_PID=""
else
  docker run -p 8000:8000 amazon/dynamodb-local \
    -jar DynamoDBLocal.jar -inMemory \
    > /tmp/dynamodb-local.log 2>&1 &
  DYNAMODB_PID=$!
  sleep 2  # Give DynamoDB a moment to initialize
  print_ok "DynamoDB running on port 8000 (PID $DYNAMODB_PID)"
fi

# ─── Step 4: Build the backend Lambda function ───────────────────────────────
# SAM packages the Python code and its dependencies into a format AWS Lambda understands
print_step "Building backend (sam build)"

cd "$BACKEND_DIR"
sam build 2>&1 | tail -5
print_ok "Backend built successfully"

# ─── Step 5: Start the backend API server ────────────────────────────────────
# SAM runs the Lambda function locally and exposes it as an HTTP API on port 3000
print_step "Starting backend API server"

if lsof -i:3000 &>/dev/null; then
  print_warn "Port 3000 already in use — assuming SAM is already running"
  SAM_PID=""
else
  sam local start-api \
    --env-vars "$BACKEND_DIR/env.json" \
    --port 3000 \
    > /tmp/sam-local.log 2>&1 &
  SAM_PID=$!
  sleep 3  # Wait for SAM to finish initializing
  print_ok "Backend API running on http://127.0.0.1:3000 (PID $SAM_PID)"
fi

# ─── Step 6: Install frontend dependencies if needed ─────────────────────────
# npm install only runs if node_modules doesn't exist yet — fast on repeat runs
print_step "Checking frontend dependencies"

cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  print_warn "node_modules not found — running npm install"
  npm install --silent
  print_ok "Dependencies installed"
else
  print_ok "Dependencies already installed"
fi

# ─── Step 7: Start the frontend dev server ───────────────────────────────────
# Vite serves the frontend on port 5173 and proxies API calls to port 3000
print_step "Starting frontend dev server"

if lsof -i:5173 &>/dev/null; then
  print_warn "Port 5173 already in use — assuming Vite is already running"
  VITE_PID=""
else
  npm run dev > /tmp/vite.log 2>&1 &
  VITE_PID=$!
  sleep 2
  print_ok "Frontend running on http://localhost:5173 (PID $VITE_PID)"
fi

# ─── Step 8: Open the browser ────────────────────────────────────────────────
# Automatically opens the app in your default browser (Mac only)
print_step "Opening browser"
sleep 1
open "http://localhost:5173" 2>/dev/null || print_warn "Could not auto-open browser — visit http://localhost:5173 manually"

# ─── Summary ─────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "   Everything is running!"
echo -e "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "   ${BOLD}Frontend:${RESET}  http://localhost:5173"
echo -e "   ${BOLD}Backend:${RESET}   http://127.0.0.1:3000"
echo -e "   ${BOLD}DynamoDB:${RESET}  http://127.0.0.1:8000"
echo -e ""
echo -e "   ${YELLOW}Press Ctrl+C to stop all servers${RESET}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"

# Keep the script alive so Ctrl+C can cleanly shut everything down
wait
