import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = DATA_DIR / "audit_assistant.sqlite3"

MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_TEXT_LENGTH = 100_000
PREVIEW_LIMIT = 2_000
SUPPORTED_EXTENSIONS = {".pdf", ".doc", ".docx"}
APP_ENV = (os.getenv("APP_ENV") or os.getenv("ENV") or "dev").strip().lower()


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


AUDIT_MODEL_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
AUDIT_MODEL_BASE_URL = (
    os.getenv("OPENAI_BASE_URL")
    or os.getenv("LLM_BASE_URL")
    or "https://api.openai.com/v1"
).rstrip("/")
AUDIT_MODEL_NAME = os.getenv("OPENAI_MODEL") or os.getenv("LLM_MODEL") or "gpt-4.1-mini"

AUDIT_PROVIDER = (os.getenv("AUDIT_PROVIDER") or "deepseek").strip().lower()
AUDIT_PROFILE = (os.getenv("AUDIT_PROFILE") or "prod").strip().lower()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY")
DEEPSEEK_BASE_URL = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-flash"
DEEPSEEK_THINKING_DISABLED = _get_bool("DEEPSEEK_THINKING_DISABLED", True)

if AUDIT_PROFILE == "debug":
    DEFAULT_TIMEOUT = "60"
    DEFAULT_RETRIES = "2"
    DEFAULT_BACKOFF = "2.0"
    DEFAULT_MAX_TOKENS = "900"
else:
    DEFAULT_TIMEOUT = "20"
    DEFAULT_RETRIES = "0"
    DEFAULT_BACKOFF = "0.5"
    DEFAULT_MAX_TOKENS = "420"

AUDIT_MODEL_TIMEOUT_SECONDS = float(os.getenv("AUDIT_MODEL_TIMEOUT_SECONDS", DEFAULT_TIMEOUT))
AUDIT_MODEL_MAX_RETRIES = int(os.getenv("AUDIT_MODEL_MAX_RETRIES", DEFAULT_RETRIES))
AUDIT_MODEL_RETRY_BACKOFF_SECONDS = float(os.getenv("AUDIT_MODEL_RETRY_BACKOFF_SECONDS", DEFAULT_BACKOFF))
AUDIT_MODEL_MAX_INPUT_CHARS = int(os.getenv("AUDIT_MODEL_MAX_INPUT_CHARS", "6000"))
AUDIT_MODEL_MAX_OUTPUT_TOKENS = int(os.getenv("AUDIT_MODEL_MAX_OUTPUT_TOKENS", DEFAULT_MAX_TOKENS))
AUDIT_ALLOW_MOCK_FALLBACK = _get_bool("AUDIT_ALLOW_MOCK_FALLBACK", True)
AUDIT_REQUIRE_CONTRACT_KEYWORDS = _get_bool("AUDIT_REQUIRE_CONTRACT_KEYWORDS", True)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
ALLOW_DEMO_USER_FALLBACK = _get_bool(
    "ALLOW_DEMO_USER_FALLBACK",
    APP_ENV not in {"prod", "production"},
)
DEMO_USER_FALLBACK_VALUE = (os.getenv("DEMO_USER_FALLBACK_VALUE") or "demo-user").strip()

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
