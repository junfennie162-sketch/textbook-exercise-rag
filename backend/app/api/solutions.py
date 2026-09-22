"""4.4 解析结果历史：列表查询、详情查看、删除。

供前端「历史结果」页与离线复评脚本使用；数据来自 SQLite（solutions 及其引用来源子表）。
"""
from fastapi import APIRouter, HTTPException, Query

from app.store import documents as doc_store

router = APIRouter(prefix="/api/solutions", tags=["解析结果"])


@router.get("", summary="解析结果列表")
async def list_solutions(
    limit: int = Query(50, ge=1, le=500, description="返回条数上限"),
    keyword: str | None = Query(None, description="按题干或解析内容模糊筛选"),
    status: str | None = Query(None, description="按状态筛选：ok / blocked"),
) -> dict:
    items = doc_store.list_solutions(limit=limit, keyword=keyword, status=status)
    return {"total": doc_store.count_solutions(keyword=keyword, status=status),
            "returned": len(items), "items": items}


@router.get("/{solution_id}", summary="解析结果详情")
async def get_solution(solution_id: str) -> dict:
    solution = doc_store.load_solution(solution_id)
    if solution is None:
        raise HTTPException(status_code=404, detail="解析结果不存在")
    return solution


@router.delete("/{solution_id}", summary="删除解析结果")
async def delete_solution(solution_id: str) -> dict:
    if not doc_store.delete_solution(solution_id):
        raise HTTPException(status_code=404, detail="解析结果不存在")
    return {"status": "success", "solution_id": solution_id,
            "message": "已删除该解析结果及其引用来源"}
