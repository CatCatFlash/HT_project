from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = DATA_DIR / "audit_assistant.sqlite3"

MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_TEXT_LENGTH = 100_000
PREVIEW_LIMIT = 2_000
SUPPORTED_EXTENSIONS = {".pdf", ".doc", ".docx"}

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
