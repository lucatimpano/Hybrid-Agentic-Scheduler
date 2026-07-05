#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'

cleanup() {
    echo -e "\n${RED}Arresto...${NC}"
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── controlli preliminari ──
if [ ! -d "$ROOT_DIR/.venv" ]; then
    echo -e "${RED}Errore: .venv non trovato. Crealo con:${NC}"
    echo "  python3 -m venv .venv"
    echo "  source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

if [ ! -d "$ROOT_DIR/ui/node_modules" ]; then
    echo -e "${CYAN}npm install in corso...${NC}"
    (cd "$ROOT_DIR/ui" && npm install)
fi

if [ ! -f "$ROOT_DIR/.env" ]; then
    echo -e "${RED}Errore: .env non trovato. Copia .env.example e inserisci GEMINI_API_KEY.${NC}"
    exit 1
fi

# ── avvio backend ──
echo -e "${GREEN}Avvio backend (FastAPI)...${NC}"
PYTHONPATH="$ROOT_DIR" "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/src/server.py" &
BACKEND_PID=$!
sleep 2

# ── avvio frontend ──
echo -e "${GREEN}Avvio frontend (Vite)...${NC}"
(cd "$ROOT_DIR/ui" && npm run dev) &
FRONTEND_PID=$!

echo -e "${CYAN}── SmartScheduler avviato ──${NC}"
echo -e "  Backend:  ${CYAN}http://localhost:8000${NC}"
echo -e "  Frontend: ${CYAN}http://localhost:5173${NC}"
echo -e "  Premi Ctrl+C per fermare tutto.${NC}"

wait "$FRONTEND_PID"
