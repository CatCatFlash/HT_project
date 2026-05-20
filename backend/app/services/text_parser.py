from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from ..exceptions import ParseError


def parse_contract_bytes(filename: str, content: bytes) -> tuple[str, int | None]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(content)
    if suffix == ".docx":
        return _parse_docx(content)
    if suffix == ".doc":
        raise ParseError(
            "PARSE_UNSUPPORTED_DOC",
            "当前 V1 暂不稳定支持 .doc 解析，请转换为 .docx 或直接粘贴文本",
            400,
        )
    raise ParseError("PARSE_UNSUPPORTED_TYPE", "不支持的文件类型", 400)


def normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    compact = "\n".join(line for line in lines if line)
    return compact.strip()


def _parse_pdf(content: bytes) -> tuple[str, int | None]:
    try:
        reader = PdfReader(BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = normalize_text("\n".join(pages))
    except Exception as exc:
        raise ParseError("PARSE_PDF_FAILED", "PDF 解析失败，请重新上传或改为粘贴文本", 400) from exc
    if not text:
        raise ParseError("PARSE_EMPTY_CONTENT", "未提取到有效 PDF 文本，请检查文件是否为文本型 PDF", 400)
    return text, len(reader.pages)


def _parse_docx(content: bytes) -> tuple[str, int | None]:
    try:
        document = Document(BytesIO(content))
        text = normalize_text("\n".join(paragraph.text for paragraph in document.paragraphs))
    except Exception as exc:
        raise ParseError("PARSE_DOCX_FAILED", "Word 解析失败，请重新上传或改为粘贴文本", 400) from exc
    if not text:
        raise ParseError("PARSE_EMPTY_CONTENT", "未提取到有效 Word 文本，请检查文件内容", 400)
    return text, None
