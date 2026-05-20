import re
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
    normalized = text.replace("\ufeff", "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    lines = [line.strip() for line in normalized.split("\n")]
    compact = "\n".join(line for line in lines if line)
    return compact.strip()


def assess_text_readability(text: str) -> dict[str, float | bool | int]:
    sample = text.strip()
    length = len(sample)
    if not sample:
        return {
            "is_readable": False,
            "question_ratio": 1.0,
            "replacement_ratio": 0.0,
            "cjk_ratio": 0.0,
            "alnum_ratio": 0.0,
            "length": 0,
        }

    question_count = sample.count("?") + sample.count("？")
    replacement_count = sample.count("\ufffd")
    cjk_count = sum(1 for char in sample if "\u4e00" <= char <= "\u9fff")
    alnum_count = sum(1 for char in sample if char.isalnum())
    question_ratio = question_count / length
    replacement_ratio = replacement_count / length
    cjk_ratio = cjk_count / length
    alnum_ratio = alnum_count / length
    is_readable = not (
        replacement_ratio >= 0.02
        or question_ratio >= 0.35
        or (length >= 20 and alnum_ratio < 0.2 and cjk_ratio < 0.1)
    )
    return {
        "is_readable": is_readable,
        "question_ratio": round(question_ratio, 4),
        "replacement_ratio": round(replacement_ratio, 4),
        "cjk_ratio": round(cjk_ratio, 4),
        "alnum_ratio": round(alnum_ratio, 4),
        "length": length,
    }


def _parse_pdf(content: bytes) -> tuple[str, int | None]:
    try:
        reader = PdfReader(BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = normalize_text("\n".join(pages))
    except Exception as exc:
        raise ParseError("PARSE_PDF_FAILED", "PDF 解析失败，请重新上传或改为粘贴文本", 400) from exc
    if not text:
        raise ParseError("PARSE_EMPTY_CONTENT", "未提取到有效 PDF 文本，请检查文件是否为文本型 PDF", 400)
    _ensure_text_readable(text, "PDF")
    return text, len(reader.pages)


def _parse_docx(content: bytes) -> tuple[str, int | None]:
    try:
        document = Document(BytesIO(content))
        segments = [paragraph.text for paragraph in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    segments.append(" | ".join(cells))
        text = normalize_text("\n".join(segments))
    except Exception as exc:
        raise ParseError("PARSE_DOCX_FAILED", "Word 解析失败，请重新上传或改为粘贴文本", 400) from exc
    if not text:
        raise ParseError("PARSE_EMPTY_CONTENT", "未提取到有效 Word 文本，请检查文件内容", 400)
    _ensure_text_readable(text, "Word")
    return text, None


def _ensure_text_readable(text: str, source_label: str) -> None:
    readability = assess_text_readability(text)
    if readability["is_readable"]:
        return
    raise ParseError(
        "PARSE_TEXT_UNREADABLE",
        f"{source_label} 提取结果可读性较差，疑似存在乱码或内容缺失，请重新导出后上传，或改为直接粘贴文本",
        400,
    )
