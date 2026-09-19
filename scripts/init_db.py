"""数据库初始化脚本：建表 + 迁移历史 JSON 数据（幂等，可重复执行）。

用法（项目根目录或 backend 目录下均可）：
    python scripts/init_db.py            # 建表 + 迁移历史 JSON 数据
    python scripts/init_db.py --check    # 只查看当前库内记录数

迁移内容（旧版运行期数据 → SQLite）：
    backend/data/documents/documents.json           → documents 表
    backend/data/documents/{doc_id}_units.json      → document_units 表
    backend/data/solutions/*.json                   → solutions + solution_sources 表
迁移完成后旧 JSON 文件保留原处作为备份，但不再被程序读取。
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "backend"))

from app.core.config import Settings            # noqa: E402
from app.store import documents as doc_store    # noqa: E402
from app.store.db import connect, init_db       # noqa: E402

# 迁移需要读写真实数据目录，这里显式加载 backend/.env，避免受当前工作目录影响
settings = Settings(_env_file=BASE_DIR / "backend" / ".env")


def infer_mode(answer_text: str) -> str:
    """旧数据没有 mode 字段：离线模板生成的解析正文带有明确标注，据此回填。"""
    return "mock" if "离线模板模式" in (answer_text or "") else "live"


def migrate_documents() -> tuple[int, int]:
    registry = settings.documents_dir / "documents.json"
    if not registry.exists():
        return 0, 0
    docs = json.loads(registry.read_text(encoding="utf-8"))
    unit_total = 0
    for doc in docs:
        doc_store.save_document({key: value for key, value in doc.items()
                                 if key != "units_file"})
        units_file = settings.documents_dir / f"{doc['doc_id']}_units.json"
        if units_file.exists():
            units = json.loads(units_file.read_text(encoding="utf-8"))
            doc_store.save_units(doc["doc_id"], units)
            unit_total += len(units)
    return len(docs), unit_total


def backfill_content_hash() -> int:
    """为缺少内容指纹的历史文档回填 SHA-256（上传时用于查重）。"""
    updated = 0
    for doc in doc_store.load_documents():
        if doc.get("content_hash"):
            continue
        upload_file = settings.upload_dir / (doc.get("stored_name") or "")
        if not upload_file.exists():
            continue
        digest = hashlib.sha256(upload_file.read_bytes()).hexdigest()
        doc_store.save_document({**doc, "content_hash": digest})
        updated += 1
    return updated


def seed_samples() -> list[str]:
    """初始化数据：把 data/samples 下的样例教材与习题册入库（已存在则跳过）。

    复用生产入库逻辑（app.api.upload._index_document），保证脚本入库与页面上传行为一致。
    """
    import shutil
    import uuid

    from app.api.upload import _index_document

    samples = (("textbook", "样例教材_高中数学基础章节.docx"),
               ("exercise", "样例习题册_高中数学60题.docx"))
    messages: list[str] = []
    for doc_type, filename in samples:
        source = settings.samples_dir / filename
        if not source.exists():
            messages.append(f"{filename}：样例不存在，跳过（先运行 scripts/make_samples.py）")
            continue
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if doc_store.find_document_by_hash(digest, doc_type):
            messages.append(f"{filename}：已在库中，跳过")
            continue
        doc_id = uuid.uuid4().hex[:12]
        stored_name = f"{doc_id}{source.suffix.lower()}"
        target = settings.upload_dir / stored_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        try:
            doc = _index_document(doc_id, doc_type, filename, stored_name, target, digest)
        except Exception as exc:
            target.unlink(missing_ok=True)
            doc_store.delete_document(doc_id)
            messages.append(f"{filename}：入库失败（{exc}）")
            continue
        messages.append(f"{filename}：入库 {doc['units_count']} 单元 / {doc['chunks_count']} 知识块")
    return messages


def clean_orphan_uploads(dry_run: bool = False) -> tuple[int, int]:
    """清理 data/uploads 下已无文档记录引用的文件，返回 (数量, 字节数)。

    孤儿文件通常来自早期失败的入库或已删除文档的残留；清理前会先列出清单。
    """
    used = {doc.get("stored_name") for doc in doc_store.load_documents()}
    orphans = [path for path in sorted(settings.upload_dir.glob("*"))
               if path.is_file() and path.name not in used]
    if not orphans:
        print("[清理] 没有孤儿文件")
        return 0, 0
    total = sum(path.stat().st_size for path in orphans)
    print(f"[清理] 发现 {len(orphans)} 个孤儿文件（合计 {total / 1024:.0f} KB）：")
    for path in orphans:
        print(f"        {path.name}  {path.stat().st_size / 1024:.0f} KB")
    if dry_run:
        print("[清理] 仅预览，未删除（去掉 --dry-run 即执行删除）")
        return 0, 0
    for path in orphans:
        path.unlink()
    print(f"[清理] 已删除 {len(orphans)} 个孤儿文件，释放 {total / 1024:.0f} KB")
    return len(orphans), total


def migrate_solutions() -> int:
    count = 0
    for path in sorted(settings.solutions_dir.glob("*.json")):
        solution = json.loads(path.read_text(encoding="utf-8"))
        solution.setdefault("mode", infer_mode(solution.get("answer_text", "")))
        doc_store.save_solution(solution)
        count += 1
    return count


def report() -> None:
    with connect() as conn:
        tables = ["documents", "document_units", "solutions", "solution_sources",
                  "batch_jobs", "batch_tasks"]
        print(f"数据库文件：{settings.data_dir / 'app.db'}")
        for table in tables:
            total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:18} {total:>5} 行")


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化数据库并迁移历史 JSON 数据")
    parser.add_argument("--check", action="store_true", help="只查看记录数，不执行迁移")
    parser.add_argument("--clean-orphans", action="store_true",
                        help="清理 data/uploads 下无文档记录引用的孤儿文件")
    parser.add_argument("--dry-run", action="store_true", help="与 --clean-orphans 搭配：只列清单不删除")
    parser.add_argument("--seed-samples", action="store_true",
                        help="初始化数据：把 data/samples 下的样例教材与习题册入库（已存在则跳过）")
    args = parser.parse_args()

    path = init_db()
    print(f"[建表] 完成（幂等）：{path}")

    if args.check:
        report()
        return

    if args.seed_samples:
        for message in seed_samples():
            print(f"[初始化数据] {message}")
        report()
        return

    if args.clean_orphans:
        clean_orphan_uploads(dry_run=args.dry_run)
        return

    docs, units = migrate_documents()
    solutions = migrate_solutions()
    hashes = backfill_content_hash()
    print(f"[迁移] 文档 {docs} 份 / 页段 {units} 条 / 解析结果 {solutions} 份 / 内容指纹回填 {hashes} 份")
    print("[说明] 旧 JSON 文件保留作为备份，程序已改为只读数据库")
    report()


if __name__ == "__main__":
    main()
