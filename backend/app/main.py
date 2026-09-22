"""应用入口：创建 FastAPI 实例、注册路由、启动时准备运行期目录。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (batch, documents, eval as eval_api, export, gaps, health, llm as llm_api,
                     settings as settings_api, solve, solutions, sources, upload)
from app.core.config import get_settings
from app.store.db import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动时准备运行期目录并确保数据库表结构存在（lifespan 已取代废弃的 on_event）。"""
    for path in (settings.data_dir, settings.upload_dir, settings.documents_dir,
                 settings.solutions_dir, settings.reports_dir):
        path.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (health, llm_api, settings_api, upload, documents, solve, sources,
               solutions, batch, export, eval_api, gaps):
    app.include_router(module.router)
