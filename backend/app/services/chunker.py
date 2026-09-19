"""2.1 切块策略：语义边界优先 + 超长块固定长度二次切分（带 overlap）。"""
import re

CHAPTER_PATTERN = re.compile(r"第\s*[一二三四五六七八九十百0-9０-９]+\s*[章讲][^\n，。]{0,30}")
# 小节标题：行首的「3.3 对数与对数运算」这类编号
SECTION_PATTERN = re.compile(r"^\s*(\d+(?:[.．]\d+){1,2})\s*[、.．]?\s*([^\n，。]{0,30})")


def detect_chapter(text: str, previous: str | None) -> str | None:
    """从文本中识别章节标题，识别不到沿用上一单元的章节。"""
    match = CHAPTER_PATTERN.search(text)
    if match:
        return match.group(0).strip()
    return previous


def detect_section(text: str, previous: str | None) -> str | None:
    """识别小节标题（如「3.3 对数与对数运算」），识别不到沿用上一单元。"""
    match = SECTION_PATTERN.search(text)
    if not match:
        return previous
    title = match.group(2).strip()
    return f"{match.group(1)} {title}".strip() if title else match.group(1)


def chunk_text(text: str, max_size: int = 600, overlap: int = 80) -> list[str]:
    """语义边界切块：段落聚合；单段超长时固定长度二次切分。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    chunks: list[str] = []
    buffer = ""
    for para in paragraphs:
        for piece in _split_oversized(para, max_size, overlap):
            if len(buffer) + len(piece) + 1 <= max_size:
                buffer = f"{buffer}\n{piece}" if buffer else piece
            else:
                if buffer:
                    chunks.append(buffer.strip())
                buffer = piece
    if buffer.strip():
        chunks.append(buffer.strip())
    return chunks


def build_chunks(units: list[dict], doc_id: str, source_file: str,
                 max_size: int = 600, overlap: int = 80) -> list[dict]:
    """把解析单元切成带来源元数据的块（页码 + 章节 + 小节 + 文件名）。"""
    all_chunks: list[dict] = []
    previous_chapter: str | None = None
    previous_section: str | None = None
    for unit in units:
        content = unit.get("content", "")
        if not content:
            continue
        previous_chapter = detect_chapter(content, previous_chapter)
        previous_section = detect_section(content, previous_section)
        for i, chunk in enumerate(chunk_text(content, max_size, overlap)):
            all_chunks.append({
                "chunk_id": f"{doc_id}-u{unit['unit_index']}-c{i}",
                "text": chunk,
                "metadata": {
                    "doc_id": doc_id,
                    "source_file": source_file,
                    "page_number": unit["unit_index"] + 1,
                    "chapter": previous_chapter or "未识别章节",
                    "section": previous_section or "未识别小节",
                },
            })
    return all_chunks


def _split_oversized(paragraph: str, max_size: int, overlap: int) -> list[str]:
    """超长段落按固定长度切分，相邻块保留 overlap 重叠。"""
    if len(paragraph) <= max_size:
        return [paragraph]
    pieces: list[str] = []
    start = 0
    step = max(max_size - overlap, 1)
    while start < len(paragraph):
        pieces.append(paragraph[start:start + max_size])
        start += step
    return pieces
