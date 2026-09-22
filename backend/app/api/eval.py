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
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # 报告被截断/手工编辑坏掉时给可读提示，而不是让接口 500
        return {"available": False, "file": latest.name,
                "error": "报告文件解析失败，请重新运行评测脚本生成"}
    return {"available": True, "file": latest.name, **payload}


@router.get("/ablation", summary="最近一次检索消融实验报告")
async def latest_ablation() -> dict:
    """供「评测」面板的检索实验对比视图读取（只读，不触发任何实验）。"""
    reports = list(get_settings().reports_dir.glob("ablation_*.json"))
    if not reports:
        return {"available": False}
    latest = max(reports, key=lambda path: path.stat().st_mtime)
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"available": False, "file": latest.name,
                "error": "报告文件解析失败，请重新运行检索消融脚本"}
    return {"available": True, "file": latest.name, **payload}
