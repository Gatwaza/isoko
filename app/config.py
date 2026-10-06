"""Runtime configuration, read from environment variables (see .env.example)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# Postgres (e.g. Supabase pooler URL). When unset, a local SQLite file is used.
DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR.parent / "data" / "isoko.db"))
CORPUS_PATH = os.getenv("CORPUS_PATH", str(BASE_DIR / "kb" / "corpus.json"))

# LLM provider: "ollama" (default, open-source, self-hosted), "openai_compat"
# (any OpenAI-compatible server, e.g. vLLM / llama.cpp / TGI hosted in Rwanda),
# or "none" (pure retrieval: returns curated passages verbatim).
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "45"))

# Small open models write poor Kinyarwanda. When false, Kinyarwanda answers are
# assembled from the curated, human-reviewed Kinyarwanda text in the corpus
# instead of being generated, so farmers never receive machine-invented
# Kinyarwanda. Flip to true once a model passes the Kinyarwanda benchmark.
GENERATE_KINYARWANDA = _bool("GENERATE_KINYARWANDA", False)

# Retrieval score below which a question is treated as out-of-scope and escalated
# to a human extension officer rather than answered.
MIN_RETRIEVAL_SCORE = float(os.getenv("MIN_RETRIEVAL_SCORE", "3.0"))

# Comma-separated API keys accepted on the benchmark / partner API.
API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "demo-benchmark-key").split(",") if k.strip()}
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")

# Africa's Talking SMS. When unset, SMS are written to the outbox table only.
AT_USERNAME = os.getenv("AT_USERNAME", "")
AT_API_KEY = os.getenv("AT_API_KEY", "")
AT_SENDER_ID = os.getenv("AT_SENDER_ID", "")
AT_SANDBOX = _bool("AT_SANDBOX", True)

# Salt for hashing phone numbers before analytics (Law N° 058/2021 data minimisation).
PHONE_HASH_SALT = os.getenv("PHONE_HASH_SALT", "change-me-in-production")

# Labels the dashboard as simulated data (used with scripts/seed_demo.py for demos).
DEMO_MODE = _bool("DEMO_MODE", False)

# Run post-response work (SMS sends, async answers) inline before responding. Needed on
# serverless hosts (Vercel) where work after the response is not guaranteed to run.
INLINE_TASKS = _bool("INLINE_TASKS", bool(os.getenv("VERCEL")))

# Model service (speech, photo diagnosis, translation). See ml_service/.
ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "")
ML_TOKEN = os.getenv("ML_TOKEN", "")
ML_TIMEOUT_S = float(os.getenv("ML_TIMEOUT_S", "60"))

# Admin keys (refinement-window knowledge import). Separate from benchmark keys.
ADMIN_KEYS = {k.strip() for k in os.getenv("ADMIN_KEYS", "").split(",") if k.strip()}

# Requests per minute: per API key, and per IP for the public demo endpoints.
RATE_LIMIT_KEY = int(os.getenv("RATE_LIMIT_KEY", "120"))
RATE_LIMIT_DEMO = int(os.getenv("RATE_LIMIT_DEMO", "20"))

# WhatsApp Cloud API (optional). Webhook: GET/POST /whatsapp/webhook
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

VERSION = "0.2.0"

# Back-pressure: at most this many LLM generations at once; extra requests get curated text immediately.
LLM_MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY", "2"))
