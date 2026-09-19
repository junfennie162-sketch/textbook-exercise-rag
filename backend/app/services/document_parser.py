"""1.3 文档解析：PDF 按页、Word 按段，输出统一结构单元列表。"""
from pathlib import Path

import docx as docx_lib
import pypdf


def parse_pdf(path: Path) -> list[dict]:
    """解析 PDF，返回每页一个单元。"""
    reader = pypdf.PdfReader(str(path))
    units: list[dict] = []
    for idx, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        text = _normalize(text)
        units.append({
            "unit_index": idx,
            "kind": "page",
            "content": text,
            "char_count": len(text),
        })
    return units


def parse_docx(path: Path) -> list[dict]:
    """解析 Word，返回非空段落一个单元。"""
    document = docx_lib.Document(str(path))
    units: list[dict] = []
    for para in document.paragraphs:
        text = _normalize(para.text)
        if not text:
            continue
        units.append({
            "unit_index": len(units),
            "kind": "paragraph",
            "content": text,
            "char_count": len(text),
            "style": para.style.name if para.style is not None else "",
        })
    return units


def parse_document(path: Path) -> list[dict]:
    """按扩展名分派解析，返回统一结构单元。"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix == ".docx":
        return parse_docx(path)
    raise ValueError(f"不支持的文档格式：{suffix}")


def _normalize(text: str) -> str:
    """去掉多余空白，但保留换行结构。"""
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
