"""1.2 习题册与教材章节上传：校验格式 -> 内容查重 -> 保存 -> 解析入库。"""
import hashlib
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import get_settings
from app.services import chunker, document_parser, vector_store
from app.store import documents as doc_store

router = APIRouter(prefix="/api/upload", tags=["资料上传"])

ALLOWED_EXTENSIONS = {".pdf", ".docx"}


def _is_allowed_file(filename: str | None) -> bool:
    if not filename:
        return False
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


async def _save_upload(file: UploadFile, doc_type: str) -> dict:
    cfg = get_settings()
    if not _is_allowed_file(file.filename):
        raise HTTPException(status_code=400, detail="仅支持 PDF 和 Word(.docx) 格式")

    suffix = Path(file.filename).suffix.lower()
    doc_id = uuid.uuid4().hex[:12]
    stored_name = f"{doc_id}{suffix}"

    upload_path = cfg.upload_dir / stored_name
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    digest = hashlib.sha256()
    with upload_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > cfg.max_upload_bytes:
                out.close()
                upload_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400,
                                    detail=f"文件超过 {cfg.max_upload_mb}MB 限制")
            digest.update(chunk)
            out.write(chunk)

    # 内容查重：同一份文件重复上传会在知识库里堆积重复知识块、污染依据召回
    content_hash = digest.hexdigest()
    duplicate = doc_store.find_document_by_hash(content_hash, doc_type)
    if duplicate is not None:
        upload_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=409,
            detail=(f"该文件内容已入库：《{duplicate['original_name']}》"
                    f"（{duplicate['units_count']} 单元 / {duplicate['chunks_count']} 知识块，"
                    f"doc_id={duplicate['doc_id']}）。如需重新导入，请先在「资料查看」中删除原文档。"),
        )

    try:
        return _index_document(doc_id, doc_type, file.filename or stored_name,
                               stored_name, upload_path, content_hash)
    except HTTPException:
        # 解析/切块阶段的拒绝（如扫描版 PDF 无文本）：同样要清理临时文件与登记记录
        upload_path.unlink(missing_ok=True)
        doc_store.delete_document(doc_id)
        raise
    except Exception as exc:
        # 入库中途失败：清理文件与可能已写入的登记记录（页段随外键级联删除）
        upload_path.unlink(missing_ok=True)
        doc_store.delete_document(doc_id)
        raise HTTPException(status_code=500, detail=f"文档解析入库失败：{exc}") from exc


def _index_document(doc_id: str, doc_type: str, original_name: str,
                    stored_name: str, upload_path: Path, content_hash: str) -> dict:
    cfg = get_settings()
    units = document_parser.parse_document(upload_path)
    if not units:
        raise HTTPException(status_code=400, detail="未能从文档中提取到任何文本内容")

    # 切块是纯计算：先算好，便于把文档记录（含单元数与块数）一次写全
    chunks = chunker.build_chunks(units, doc_id, original_name,
                                  cfg.chunk_max_size, cfg.chunk_overlap)
    if not chunks:
        # 页段存在但正文全空（典型：扫描版/图片型 PDF）：入库只会得到空知识库，
        # 且内容指纹已存在会让修复后的同名文件再次上传被 409 挡住——必须当场拒绝
        raise HTTPException(
            status_code=400,
            detail="文档未能提取到可入库文本（可能为扫描版/图片型 PDF），请提供含文本层的文件",
        )
    for chunk in chunks:
        chunk["metadata"]["doc_type"] = doc_type

    doc = {
        "doc_id": doc_id,
        "doc_type": doc_type,
        "original_name": original_name,
        "stored_name": stored_name,
        "units_count": len(units),
        "chunks_count": len(chunks),
        "status": "indexed",
        "content_hash": content_hash,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    # 先写文档记录，再写页段（页段表有外键指向文档表）
    doc_store.save_document(doc)
    doc_store.save_units(doc_id, units)

    store = vector_store.VectorStore(cfg)
    store.add_chunks(chunks)

    # 同步 BM25 词法索引（混合检索稀疏路），失败不影响向量入库结果
    try:
        from app.services.lexical_index import get_lexical_index
        get_lexical_index().add_chunks(chunks)
    except Exception:
        pass

    return doc


@router.post("/exercise", summary="上传习题册")
async def upload_exercise(file: UploadFile = File(...)) -> dict:
    doc = await _save_upload(file, "exercise")
    return {"status": "success", "message": "习题册上传成功", "document": doc}


@router.post("/textbook", summary="上传教材章节")
async def upload_textbook(file: UploadFile = File(...)) -> dict:
    doc = await _save_upload(file, "textbook")
    return {"status": "success", "message": "教材章节上传成功", "document": doc}
