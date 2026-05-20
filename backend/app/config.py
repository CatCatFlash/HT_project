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
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY")
DEEPSEEK_BASE_URL = (os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-pro"
AUDIT_MODEL_TIMEOUT_SECONDS = float(os.getenv("AUDIT_MODEL_TIMEOUT_SECONDS", "30"))
AUDIT_MODEL_MAX_RETRIES = int(os.getenv("AUDIT_MODEL_MAX_RETRIES", "1"))
AUDIT_MODEL_RETRY_BACKOFF_SECONDS = float(os.getenv("AUDIT_MODEL_RETRY_BACKOFF_SECONDS", "1.0"))
AUDIT_MODEL_MAX_INPUT_CHARS = int(os.getenv("AUDIT_MODEL_MAX_INPUT_CHARS", "12000"))
AUDIT_ALLOW_MOCK_FALLBACK = _get_bool("AUDIT_ALLOW_MOCK_FALLBACK", True)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
