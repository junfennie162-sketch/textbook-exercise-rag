"""业务数据仓库（SQLite）：文档与页段、解析结果与引用来源、批量任务记录。

对外函数名与返回结构与旧版 JSON 仓库保持一致，因此 api/ 与 services/ 调用方无需改动；
页段与引用来源改为关系表存储（原先分别是独立 JSON 文件、内嵌在解析结果 JSON 里）。
"""
import json

from app.store.db import connect


# ------------------------------------------------------------------ 文档

def _document_row(row) -> dict:
    return {
        "doc_id": row["doc_id"],
        "doc_type": row["doc_type"],
        "original_name": row["original_name"],
        "stored_name": row["stored_name"],
        "units_count": row["units_count"],
        "chunks_count": row["chunks_count"],
        "status": row["status"],
        "content_hash": row["content_hash"],
        "created_at": row["created_at"],
    }


def load_documents() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM documents ORDER BY created_at, doc_id").fetchall()
    return [_document_row(row) for row in rows]


def get_document(doc_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE doc_id = ?",
                           (doc_id,)).fetchone()
    return _document_row(row) if row else None


def save_document(doc: dict) -> dict:
    with connect() as conn:
        conn.execute(
            """INSERT INTO documents (doc_id, doc_type, original_name, stored_name,
                                      units_count, chunks_count, status, content_hash, created_at)
               VALUES (:doc_id, :doc_type, :original_name, :stored_name,
                       :units_count, :chunks_count, :status, :content_hash, :created_at)
               ON CONFLICT(doc_id) DO UPDATE SET
                   doc_type = excluded.doc_type,
                   original_name = excluded.original_name,
                   stored_name = excluded.stored_name,
                   units_count = excluded.units_count,
                   chunks_count = excluded.chunks_count,
                   status = excluded.status,
                   content_hash = excluded.content_hash""",
            {
                "doc_id": doc["doc_id"],
                "doc_type": doc["doc_type"],
                "original_name": doc["original_name"],
                "stored_name": doc.get("stored_name", ""),
                "units_count": doc.get("units_count", 0),
                "chunks_count": doc.get("chunks_count", 0),
                "status": doc.get("status", "indexed"),
                "content_hash": doc.get("content_hash"),
                "created_at": doc.get("created_at", ""),
            },
        )
    return doc


def find_document_by_hash(content_hash: str, doc_type: str) -> dict | None:
    """按内容指纹 + 资料类型查重：同一份文件重复上传时用于拦截。"""
    if not content_hash:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE content_hash = ? AND doc_type = ? LIMIT 1",
            (content_hash, doc_type),
        ).fetchone()
    return _document_row(row) if row else None


def delete_document(doc_id: str) -> dict | None:
    """从登记表移除文档（页段随外键级联删除），返回被删除的登记项。"""
    removed = get_document(doc_id)
    if removed is None:
        return None
    with connect() as conn:
        conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    return removed


def save_units(doc_id: str, units: list[dict]) -> int:
    """覆盖写入文档的页段（重新上传同一文档时按 doc_id 替换）。"""
    with connect() as conn:
        conn.execute("DELETE FROM document_units WHERE doc_id = ?", (doc_id,))
        conn.executemany(
            """INSERT INTO document_units (doc_id, unit_index, kind, content, char_count)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    doc_id,
                    unit["unit_index"],
                    unit.get("kind", "page"),
                    unit.get("content", ""),
                    unit.get("char_count", len(unit.get("content", ""))),
                )
                for unit in units
            ],
        )
    return len(units)


def load_units(doc_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT unit_index, kind, content, char_count FROM document_units
               WHERE doc_id = ? ORDER BY unit_index""",
            (doc_id,),
        ).fetchall()
    return [dict(row) for row in rows]


# ------------------------------------------------------------- 解析结果

def save_solution(solution: dict) -> None:
    """写入/覆盖解析结果，并同步其引用来源（引用来源以子表存储）。"""
    step_check = solution.get("step_check")
    with connect() as conn:
        conn.execute(
            """INSERT INTO solutions (solution_id, question_text, status, blocked_type,
                                      answer_text, step_check_json, mode, model, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(solution_id) DO UPDATE SET
                   question_text = excluded.question_text,
                   status = excluded.status,
                   blocked_type = excluded.blocked_type,
                   answer_text = excluded.answer_text,
                   step_check_json = excluded.step_check_json,
                   mode = excluded.mode,
                   model = excluded.model""",
            (
                solution["solution_id"],
                solution.get("question_text", ""),
                solution.get("status", "ok"),
                solution.get("blocked_type"),
                solution.get("answer_text", ""),
                json.dumps(step_check, ensure_ascii=False) if step_check else None,
                solution.get("mode", "live"),
                solution.get("model", ""),
                solution.get("created_at", ""),
            ),
        )
        conn.execute("DELETE FROM solution_sources WHERE solution_id = ?",
                     (solution["solution_id"],))
        sources = solution.get("sources") or {}
        if sources:
            conn.executemany(
                """INSERT INTO solution_sources (solution_id, source_key, chunk_id,
                                                 source_file, chapter, section, page_number,
                                                 relevance, low_relevance, text_snippet)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        solution["solution_id"],
                        key,
                        ref.get("chunk_id"),
                        ref.get("source_file"),
                        ref.get("chapter"),
                        ref.get("section"),
                        ref.get("page_number"),
                        ref.get("relevance"),
                        1 if ref.get("low_relevance") else 0,
                        ref.get("text_snippet"),
                    )
                    for key, ref in sources.items()
                ],
            )


def _solution_row(row, sources: dict) -> dict:
    step_check = row["step_check_json"]
    return {
        "solution_id": row["solution_id"],
        "question_text": row["question_text"],
        "status": row["status"],
        "blocked_type": row["blocked_type"],
        "answer_text": row["answer_text"],
        "step_check": json.loads(step_check) if step_check else None,
        "mode": row["mode"],
        "model": row["model"] if "model" in row.keys() else "",
        "created_at": row["created_at"],
        "sources": sources,
    }


def load_solution(solution_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM solutions WHERE solution_id = ?",
                           (solution_id,)).fetchone()
        if row is None:
            return None
        source_rows = conn.execute(
            """SELECT * FROM solution_sources WHERE solution_id = ?
               ORDER BY source_key""",
            (solution_id,),
        ).fetchall()
    sources = {
        item["source_key"]: {
            "chunk_id": item["chunk_id"],
            "source_file": item["source_file"],
            "chapter": item["chapter"],
            "section": item["section"],
            "page_number": item["page_number"],
            "relevance": item["relevance"],
            "low_relevance": bool(item["low_relevance"]),
            "text_snippet": item["text_snippet"],
        }
        for item in source_rows
    }
    return _solution_row(row, sources)


def list_solutions(limit: int = 50, keyword: str | None = None,
                   status: str | None = None) -> list[dict]:
    """解析结果列表（支持关键词与状态筛选），按时间倒序，供历史记录页使用。"""
    sql = """SELECT s.*, (SELECT COUNT(*) FROM solution_sources src
                         WHERE src.solution_id = s.solution_id) AS sources_count
             FROM solutions s WHERE 1 = 1"""
    params: list = []
    if keyword:
        sql += " AND (s.question_text LIKE ? OR s.answer_text LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if status:
        sql += " AND s.status = ?"
        params.append(status)
    sql += " ORDER BY s.created_at DESC, s.solution_id DESC LIMIT ?"
    params.append(limit)

    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "solution_id": row["solution_id"],
            "question_text": row["question_text"],
            "status": row["status"],
            "blocked_type": row["blocked_type"],
            "mode": row["mode"],
            "model": row["model"] if "model" in row.keys() else "",
            "created_at": row["created_at"],
            "sources_count": row["sources_count"],
            "answer_preview": (row["answer_text"] or "")[:120],
        }
        for row in rows
    ]


def count_solutions(keyword: str | None = None, status: str | None = None) -> int:
    """符合条件的解析结果总数（与 list_solutions 使用同一套筛选条件）。"""
    sql = "SELECT COUNT(*) FROM solutions s WHERE 1 = 1"
    params: list = []
    if keyword:
        sql += " AND (s.question_text LIKE ? OR s.answer_text LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if status:
        sql += " AND s.status = ?"
        params.append(status)
    with connect() as conn:
        return conn.execute(sql, params).fetchone()[0]


def delete_solution(solution_id: str) -> bool:
    """删除解析结果（引用来源随外键级联清理）。"""
    with connect() as conn:
        cursor = conn.execute("DELETE FROM solutions WHERE solution_id = ?",
                              (solution_id,))
    return cursor.rowcount > 0


# ------------------------------------------------------------- 批量任务

def save_batch_job(batch_id: str, total: int, created_at: str,
                   status: str = "pending") -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO batch_jobs (batch_id, total, status, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(batch_id) DO UPDATE SET total = excluded.total""",
            (batch_id, total, status, created_at),
        )


def save_batch_tasks(batch_id: str, tasks: list[dict]) -> None:
    with connect() as conn:
        conn.executemany(
            """INSERT INTO batch_tasks (batch_id, question_id, question, status)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(batch_id, question_id) DO UPDATE SET question = excluded.question""",
            [(batch_id, task["question_id"], task["question"], task.get("status", "pending"))
             for task in tasks],
        )


def update_batch_task(batch_id: str, question_id: int, status: str,
                      solution_id: str | None = None,
                      blocked_type: str | None = None,
                      error: str | None = None) -> None:
    with connect() as conn:
        conn.execute(
            """UPDATE batch_tasks SET status = ?, solution_id = ?, blocked_type = ?, error = ?
               WHERE batch_id = ? AND question_id = ?""",
            (status, solution_id, blocked_type, error, batch_id, question_id),
        )


def finish_batch_job(batch_id: str, status: str, finished_at: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE batch_jobs SET status = ?, finished_at = ? WHERE batch_id = ?",
                     (status, finished_at, batch_id))
