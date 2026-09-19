"""5.2 评测结果查看：读取 reports 目录下最新评测报告。"""
import json

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(prefix="/api/eval", tags=["评测"])


@router.get("/latest", summary="最近一次评测报告")
async def latest_eval() -> dict:
    # 按修改时间取最新：文件名排序会让 eval_regraded_* 永远压过 eval_*，与实际"最近一次"不符
    reports = list(get_settings().reports_dir.glob("eval_*.json"))
    if not reports:
        return {"available": False}
    latest = max(reports, key=lambda path: path.stat().st_mtime)
    payload = json.loads(latest.read_text(encoding="utf-8"))
    return {"available": True, "file": latest.name, **payload}
