"""SQLite 连接与建表：业务数据持久化（文档、页段、解析结果、引用来源、批量任务）。

设计说明：
  · 单库文件 backend/data/app.db，随运行期数据目录存放（不进版本库、不进源码包）；
  · 外键开启级联删除：删除解析结果时其引用来源一并清理；
  · 布尔值以 INTEGER 存储（SQLite 无布尔类型），JSON 字段以 TEXT 存储；
  · 生产写入用事务上下文（异常回滚），避免半写状态。
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.core.config import get_settings

DB_FILENAME = "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,
    doc_type      TEXT NOT NULL,
    original_name TEXT NOT NULL,
    stored_name   TEXT NOT NULL,
    units_count   INTEGER NOT NULL DEFAULT 0,
    chunks_count  INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'indexed',
    content_hash  TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_units (
    doc_id     TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    unit_index INTEGER NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'page',
    content    TEXT NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (doc_id, unit_index)
);

CREATE TABLE IF NOT EXISTS solutions (
    solution_id     TEXT PRIMARY KEY,
    question_text   TEXT NOT NULL,
    status          TEXT NOT NULL,
    blocked_type    TEXT,
    answer_text     TEXT NOT NULL DEFAULT '',
    step_check_json TEXT,
    mode            TEXT NOT NULL DEFAULT 'live',
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_solutions_created ON solutions (created_at DESC);

CREATE TABLE IF NOT EXISTS solution_sources (
    solution_id   TEXT NOT NULL REFERENCES solutions(solution_id) ON DELETE CASCADE,
    source_key    TEXT NOT NULL,
    chunk_id      TEXT,
    source_file   TEXT,
    chapter       TEXT,
    section       TEXT,
    page_number   INTEGER,
    relevance     REAL,
    low_relevance INTEGER NOT NULL DEFAULT 0,
    text_snippet  TEXT,
    PRIMARY KEY (solution_id, source_key)
);

CREATE TABLE IF NOT EXISTS batch_jobs (
    batch_id    TEXT PRIMARY KEY,
    total       INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS batch_tasks (
    batch_id     TEXT NOT NULL REFERENCES batch_jobs(batch_id) ON DELETE CASCADE,
    question_id  INTEGER NOT NULL,
    question     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    blocked_type TEXT,
    solution_id  TEXT,
    error        TEXT,
    PRIMARY KEY (batch_id, question_id)
);
"""


def db_path() -> Path:
    """数据库文件路径（随配置的数据目录）。"""
    path = get_settings().data_dir / DB_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


_initialized: set[str] = set()

# 后加的列：旧库通过 ALTER TABLE 补齐（SQLite 的 CREATE TABLE IF NOT EXISTS 不会改动已有表）
_ADDED_COLUMNS = {
    "documents": {"content_hash": "TEXT"},
    "solution_sources": {"section": "TEXT"},
}
# 依赖后加列的索引：必须在补列之后创建，否则旧库会因列不存在而报错
_ADDED_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents (content_hash, doc_type)",
)


def _migrate_columns(conn) -> None:
    """为已存在的表补齐后加的列与其索引（幂等）。"""
    for table, columns in _ADDED_COLUMNS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:                        # 表不存在时由 SCHEMA 负责创建
            continue
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    for statement in _ADDED_INDEXES:
        conn.execute(statement)


def init_db(path: Path | None = None) -> Path:
    """建表（幂等），返回数据库路径。服务启动与初始化脚本都会调用。"""
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(target)) as conn:
        conn.executescript(SCHEMA)
        _migrate_columns(conn)
        conn.commit()
    _initialized.add(str(target.resolve()))
    return target


def ensure_schema(path: Path | None = None) -> Path:
    """确保目标库已建表（进程内只做一次），使仓库函数无需依赖启动钩子。"""
    target = (path or db_path()).resolve()
    if str(target) not in _initialized:
        init_db(target)
    return target


@contextmanager
def connect(path: Path | None = None):
    """事务型连接：正常提交、异常回滚；使用前自动确保表结构存在。"""
    conn = sqlite3.connect(str(ensure_schema(path)))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
