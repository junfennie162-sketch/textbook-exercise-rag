"""3.3 引用来源追溯：按 chunk_id 查原文。"""
from fastapi import APIRouter, HTTPException

from app.services import vector_store

router = APIRouter(prefix="/api/sources", tags=["引用追溯"])


@router.get("/{chunk_id}", summary="来源详情与原文")
async def get_source(chunk_id: str) -> dict:
    store = vector_store.VectorStore()
    item = store.get(chunk_id)
    if item is None:
        raise HTTPException(status_code=404, detail="来源块不存在")
    meta = item["metadata"]
    return {
        "chunk_id": chunk_id,
        "chapter": meta.get("chapter"),
        "page_number": meta.get("page_number"),
        "source_file": meta.get("source_file"),
        "full_text": item["text"],
    }
