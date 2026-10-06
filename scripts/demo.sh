#!/usr/bin/env bash
# Isôko live demo: the app on this laptop with a local open model (Ollama), exposed on a
# public HTTPS URL through a Cloudflare quick tunnel (no account needed).
#
#   scripts/demo.sh                 # uses gemma3:4b (best on our evaluation)
#   LLM_MODEL=llama3.2 scripts/demo.sh
#   DB=local scripts/demo.sh        # local SQLite demo DB instead of Supabase
#
# Ctrl-C stops both the app and the tunnel.
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${LLM_MODEL:-gemma3:4b}"
PORT="${PORT:-8000}"
CLOUDFLARED="$(command -v cloudflared || echo "$HOME/.local/bin/cloudflared")"

curl -sf localhost:11434/api/tags >/dev/null || { echo "Ollama is not running. Start the Ollama app first."; exit 1; }
ollama show "$MODEL" >/dev/null 2>&1 || ollama pull "$MODEL"

export LLM_PROVIDER=ollama LLM_MODEL="$MODEL" DEMO_MODE=true
if [ "${DB:-supabase}" = "supabase" ] && [ -f .env.supabase ]; then
  set -a; source .env.supabase; set +a
  export API_KEYS="${BENCHMARK_API_KEY}"
else
  export DATABASE_URL="" DB_PATH=data/demo.db API_KEYS="${API_KEYS:-demo-benchmark-key}"
fi

echo "Warming up ${MODEL}..."
curl -s localhost:11434/api/generate -d "{\"model\":\"$MODEL\",\"prompt\":\"hi\",\"stream\":false,\"options\":{\"num_predict\":1}}" >/dev/null

# Model service (Kinyarwanda speech, photo diagnosis, translation) on this machine's GPU.
ML_PORT="${ML_PORT:-7860}"
if [ -d .venv-ml ]; then
  ML_TOKEN="${ML_TOKEN:-local-$(date +%s)}"
  (cd ml_service && ML_TOKEN="$ML_TOKEN" ../.venv-ml/bin/python -m uvicorn app:app --port "$ML_PORT" --log-level warning) &
  ML=$!
  export ML_SERVICE_URL="http://localhost:$ML_PORT" ML_TOKEN
else
  echo "No .venv-ml: voice and photo features disabled (see ml_service/README.md)."
  ML=""
fi

.venv/bin/python -m uvicorn app.main:app --port "$PORT" --log-level warning &
APP=$!
"$CLOUDFLARED" tunnel --no-autoupdate --url "http://localhost:$PORT" > data/tunnel.log 2>&1 &
TUN=$!
trap 'kill $APP $TUN $ML 2>/dev/null' EXIT INT TERM

for _ in $(seq 1 30); do
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' data/tunnel.log | head -1 || true)
  [ -n "$URL" ] && break; sleep 1
done
echo
echo "  Local:            http://localhost:$PORT/simulator"
echo "  Promoter portal:  ${URL:-http://localhost:$PORT}/promoter"
echo "  Public:           ${URL:-(tunnel not ready, see data/tunnel.log)}"
echo "  Live comparison:  ${URL:-http://localhost:$PORT}/compare"
echo "  Evaluation:       ${URL:-http://localhost:$PORT}/evaluation"
echo "  Dashboard:        ${URL:-http://localhost:$PORT}/dashboard"
echo "  Model:            ${MODEL} (Ollama, local)"
echo "  Model service:    ${ML_SERVICE_URL:-disabled} (internal API used by the pages above, not a web page; ~1 min to load)"
echo
wait $APP
