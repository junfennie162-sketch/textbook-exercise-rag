"""一键导入样例数据：上传 data/samples 下的教材与习题册到知识库。

用法（后端服务启动后）：
    python scripts/upload_samples.py                       # 追加导入
    python scripts/upload_samples.py --replace             # 先删除旧样例再导入（语料刷新）
    python scripts/upload_samples.py --base-url http://127.0.0.1:8001 --replace
"""
import argparse
import json
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parents[1]
SAMPLES = BASE_DIR / "data" / "samples"

UPLOADS = [
    ("textbook", "样例教材_高中数学基础章节.docx"),
    ("exercise", "样例习题册_高中数学60题.docx"),
    ("textbook", "样例教材_补充章节_三角恒等变换与直线和圆.docx"),
]

# 历史版本的样例文件名：使用 --replace 时一并清理，避免过期内容继续参与检索
LEGACY_SAMPLE_NAMES = {
    "样例习题册_高中数学15题.docx",
}


def existing_documents(client: httpx.Client, base_url: str) -> list[dict]:
    response = client.get(f"{base_url}/api/documents")
    response.raise_for_status()
    return response.json()


def delete_document(client: httpx.Client, base_url: str, doc: dict) -> None:
    response = client.delete(f"{base_url}/api/documents/{doc['doc_id']}")
    if response.status_code == 200:
        print(f"[清理] {doc['original_name']} -> 删除 {response.json()['deleted_chunks']} 个知识块")
    else:
        print(f"[清理失败] {doc['original_name']}: {response.status_code} {response.text[:160]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="上传样例文档到知识库")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--replace", action="store_true",
                        help="先删除知识库中已有的样例文档（含历史版本）再导入")
    args = parser.parse_args()

    sample_names = {filename for _, filename in UPLOADS} | LEGACY_SAMPLE_NAMES

    with httpx.Client(timeout=300, trust_env=False) as client:
        if args.replace:
            for doc in existing_documents(client, args.base_url):
                if doc.get("original_name") in sample_names:
                    delete_document(client, args.base_url, doc)

        for doc_type, filename in UPLOADS:
            path = SAMPLES / filename
            if not path.exists():
                print(f"[跳过] 样例不存在：{path}（先运行 scripts/make_samples.py）")
                continue
            with path.open("rb") as handle:
                response = client.post(
                    f"{args.base_url}/api/upload/{doc_type}",
                    files={"file": (filename, handle.read())},
                )
            if response.status_code == 200:
                doc = response.json()["document"]
                print(f"[成功] {filename} -> {doc['units_count']} 单元 / {doc['chunks_count']} 知识块")
            else:
                print(f"[失败] {filename}: {response.status_code} {response.text[:200]}")

        docs = existing_documents(client, args.base_url)
        print(json.dumps([
            {"name": d["original_name"], "chunks": d["chunks_count"]} for d in docs
        ], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
