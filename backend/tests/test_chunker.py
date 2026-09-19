from app.services.chunker import build_chunks, chunk_text, detect_chapter


def test_chunk_text_respects_max_size() -> None:
    text = "段落一内容。\n\n段落二内容更长一些，包含更多文字用来测试聚合行为。\n\n段落三。"
    chunks = chunk_text(text, max_size=50, overlap=10)
    assert all(len(c) <= 50 for c in chunks)
    assert "".join(chunks).replace("\n", "").startswith("段落一")


def test_chunk_text_oversized_paragraph_split_with_overlap() -> None:
    text = "字" * 1000
    chunks = chunk_text(text, max_size=600, overlap=80)
    assert len(chunks) >= 2
    assert chunks[0][-80:] == chunks[1][:80]


def test_detect_chapter_inherits_previous() -> None:
    assert detect_chapter("第三章 指数函数", None) == "第三章 指数函数"
    assert detect_chapter("普通正文没有章节", "第三章 指数函数") == "第三章 指数函数"


def test_build_chunks_keeps_metadata() -> None:
    units = [
        {"unit_index": 0, "kind": "page", "content": "第一章 集合\n集合具有确定性。"},
        {"unit_index": 1, "kind": "page", "content": "继续讲述集合的互异性。"},
    ]
    chunks = build_chunks(units, doc_id="abc123", source_file="教材.pdf")
    assert chunks, "应产生至少一个块"
    first = chunks[0]
    assert first["chunk_id"].startswith("abc123-")
    assert first["metadata"]["page_number"] == 1
    assert first["metadata"]["chapter"].startswith("第一章")
    assert chunks[-1]["metadata"]["page_number"] == 2
