"""Untrusted format parsing runs in a short-lived subprocess; no model imports here."""

import csv
import io
import json
import re
import sys
import zipfile
from pathlib import Path

from nexusai.documents.errors import DocumentError

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 2_000_000
MAX_BLOCKS = 10_000
MEDIA = {
    "txt": {"text/plain"},
    "csv": {"text/csv", "application/csv", "application/vnd.ms-excel"},
    "pdf": {"application/pdf"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
}


def validate_upload(data: bytes, filename: str, content_type: str) -> str:
    kind = Path(filename).suffix.lower().lstrip(".")
    if kind not in MEDIA:
        raise DocumentError("unsupported_format", 415)
    mime = content_type.split(";")[0].lower()
    if mime not in MEDIA[kind] | {"application/octet-stream", ""}:
        raise DocumentError("content_type_mismatch", 415)
    if len(data) > MAX_BYTES:
        raise DocumentError("file_too_large", 413)
    if not data:
        raise DocumentError("empty_file")
    if kind == "pdf" and not data.startswith(b"%PDF-"):
        raise DocumentError("invalid_pdf")
    if kind == "docx" and not data.startswith(b"PK"):
        raise DocumentError("invalid_docx")
    if kind in {"txt", "csv"}:
        try:
            value = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise DocumentError("utf8_required") from None
        if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
            raise DocumentError("binary_text_rejected")
    return kind


def parse(data: bytes, kind: str) -> list[dict]:
    validate_upload(data, f"source.{kind}", "")
    blocks = []
    size = 0

    def add(value: str, locator: str):
        nonlocal size
        value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not value:
            return
        size += len(value)
        if size > MAX_TEXT or len(blocks) >= MAX_BLOCKS:
            raise DocumentError("extraction_limit")
        blocks.append({"text": value, "locator": locator})

    try:
        if kind == "txt":
            for i, paragraph in enumerate(re.split(r"\n\s*\n", data.decode("utf-8-sig")), 1):
                add(paragraph, f"paragraph:{i}")
        elif kind == "csv":
            rows = csv.reader(io.StringIO(data.decode("utf-8-sig")), strict=True)
            headers = next(rows, [])
            if (
                not headers
                or any(not h.strip() for h in headers)
                or len(set(headers)) != len(headers)
            ):
                raise DocumentError("invalid_csv_headers")
            if len(headers) > 100:
                raise DocumentError("too_many_columns")
            for i, row in enumerate(rows, 2):
                if len(row) != len(headers):
                    raise DocumentError("inconsistent_csv_columns")
                add(
                    " | ".join(f"{h}: {v}" for h, v in zip(headers, row, strict=True)),
                    f"csv_record:{i}",
                )
        elif kind == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise DocumentError("encrypted_pdf")
            if len(reader.pages) > 100:
                raise DocumentError("too_many_pages")
            empty_pages = []
            for i, page in enumerate(reader.pages, 1):
                value = page.extract_text() or ""
                if not value.strip():
                    empty_pages.append(i)
                add(value, f"page:{i}")
            # Do not silently mark mixed scanned/text documents fully indexed.
            if empty_pages:
                raise DocumentError("ocr_or_blank_page_review_required")
        else:
            from docx import Document
            from docx.table import Table

            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 2000 or sum(e.file_size for e in entries) > 20 * 1024 * 1024:
                    raise DocumentError("archive_expansion_limit")
                names = set(archive.namelist())
                if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                    raise DocumentError("invalid_docx")
                if any("vbaProject" in name for name in names):
                    raise DocumentError("macro_content_rejected")
            document = Document(io.BytesIO(data))
            for i, item in enumerate(document.iter_inner_content(), 1):
                if isinstance(item, Table):
                    for row_no, row in enumerate(item.rows, 1):
                        if any(cell.tables for cell in row.cells):
                            raise DocumentError("nested_table_not_supported")
                        add(" | ".join(cell.text for cell in row.cells), f"table:{i}/row:{row_no}")
                else:
                    add(item.text, f"paragraph:{i}")
    except DocumentError:
        raise
    except Exception:
        raise DocumentError("malformed_document") from None
    if not blocks:
        raise DocumentError("no_extractable_text")
    return blocks


def main():
    try:
        path, kind = sys.argv[1:]
        result = {"blocks": parse(Path(path).read_bytes(), kind)}
    except DocumentError as error:
        result = {"error": error.code}
    except Exception:
        result = {"error": "parser_failure"}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
