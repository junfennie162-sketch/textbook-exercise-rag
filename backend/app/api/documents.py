"""1.3 资料原文与关键内容页面查看；知识库文档删除。"""
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.services import chunker
from app.store import documents as doc_store

router = APIRouter(prefix="/api/documents", tags=["资料查看"])

PREVIEW_CHARS = 50


@router.get("", summary="文档列表")
async def list_documents() -> list[dict]:
    return doc_store.load_documents()


@router.get("/{doc_id}/pages", summary="页/段摘要列表（含章节与小节）")
async def list_pages(doc_id: str) -> dict:
    doc = doc_store.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    units = doc_store.load_units(doc_id)

    # 章节与小节在切块阶段识别；这里用同一套规则回填到页段，便于按小节浏览与筛选
    pages: list[dict] = []
    chapter: str | None = None
    section: str | None = None
    for unit in units:
        content = unit.get("content", "")
        chapter = chunker.detect_chapter(content, chapter)
        section = chunker.detect_section(content, section)
        pages.append({
            "page": unit["unit_index"] + 1,
            "preview": content[:PREVIEW_CHARS],
            "char_count": unit["char_count"],
            "chapter": chapter or "未识别章节",
            "section": section or "未识别小节",
        })

    sections: dict[str, dict] = {}
    for item in pages:
        entry = sections.setdefault(item["section"], {
            "section": item["section"],
            "chapter": item["chapter"],
            "count": 0,
            "first_page": item["page"],
        })
        entry["count"] += 1

    return {
        "doc_id": doc_id,
        "doc_type": doc["doc_type"],
        "original_name": doc["original_name"],
        "total": len(units),
        "sections": list(sections.values()),
        "pages": pages,
    }


@router.get("/{doc_id}/pages/{page_no}", summary="指定页/段完整内容")
async def get_page(doc_id: str, page_no: int) -> dict:
    units = doc_store.load_units(doc_id)
    if page_no < 1 or page_no > len(units):
        raise HTTPException(status_code=404, detail="页码超出范围")
    unit = units[page_no - 1]
    return {"doc_id": doc_id, "page": page_no, "content": unit["content"]}


@router.delete("/{doc_id}", summary="从知识库删除文档")
async def delete_document(doc_id: str) -> dict:
    """删除文档的向量块、词法索引与登记项，并清理上传文件与解析中间文件。

    用于语料更新后清理旧文档，避免过期内容继续参与依据召回。
    """
    from app.core.config import get_settings
    from app.services.lexical_index import get_lexical_index
    from app.services.vector_store import VectorStore

    doc = doc_store.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")

    try:
        deleted_chunks = VectorStore().delete_document(doc_id)
        get_lexical_index().remove_document(doc_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"清理向量索引失败：{exc}") from exc

    doc_store.delete_document(doc_id)

    # 页段与引用来源随数据库级联清理；这里只需清理上传的原始文件
    cfg = get_settings()
    stored_name = doc.get("stored_name")
    if stored_name:
        (cfg.upload_dir / Path(stored_name).name).unlink(missing_ok=True)

    return {
        "status": "success",
        "doc_id": doc_id,
        "original_name": doc.get("original_name", ""),
        "deleted_chunks": deleted_chunks,
        "message": f"已删除《{doc.get('original_name', '')}》及其 {deleted_chunks} 个知识块",
    }
