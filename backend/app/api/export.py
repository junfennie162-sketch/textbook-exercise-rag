"""4.3 导出下载：FileResponse 触发浏览器下载。"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.services.exporter import export_solutions
from app.store import documents as doc_store

router = APIRouter(prefix="/api/export", tags=["导出交付"])


@router.get("/{solution_id}", summary="导出单份解析")
async def export_one(solution_id: str, fmt: str = "docx") -> FileResponse:
    sol = doc_store.load_solution(solution_id)
    if sol is None:
        raise HTTPException(status_code=404, detail="解析结果不存在")
    if fmt not in ("docx", "md"):
        raise HTTPException(status_code=400, detail="格式仅支持 docx / md")
    path = export_solutions([sol], get_settings().solutions_dir / "exports", fmt)
    return FileResponse(path, filename=path.name, media_type=_media_type(fmt))


@router.post("/file", summary="导出多份解析为一个文件")
async def export_many(solution_ids: list[str], fmt: str = "docx") -> FileResponse:
    if fmt not in ("docx", "md"):
        raise HTTPException(status_code=400, detail="格式仅支持 docx / md")
    solutions = []
    for sid in solution_ids:
        sol = doc_store.load_solution(sid)
        if sol is not None:
            solutions.append(sol)
    if not solutions:
        raise HTTPException(status_code=404, detail="没有可导出的解析结果")
    path = export_solutions(solutions, get_settings().solutions_dir / "exports", fmt)
    return FileResponse(path, filename=path.name, media_type=_media_type(fmt))


def _media_type(fmt: str) -> str:
    return ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if fmt == "docx" else "text/markdown")
