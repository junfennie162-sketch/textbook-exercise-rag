"""打包中期源码 ZIP：排除依赖目录与构建产物，保留可离线运行的模型与示例数据。

用法（项目根目录下）：
    python scripts/package_source.py
    python scripts/package_source.py --out "D:/提交/源码包.zip"
    python scripts/package_source.py --list-only     # 只打印将要打包的清单，不生成文件

打包规则：
  · 排除：虚拟环境、node_modules、__pycache__、.pytest_cache、*.egg-info、dist、.git、.claude、
          其他中期提交物，以及 **backend/.env（含真实 API Key，禁止外发）**
  · 保留：全部源码、README、.env.example、示例数据（data/samples）、评测报告、本地嵌入模型
          （models_cache，约 95MB，保证解压后无需联网即可运行）
"""
import argparse
import os
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BASE_DIR  # 以项目根目录（含 backend/frontend）为打包根
ARCHIVE_ROOT = PROJECT_DIR.name

EXCLUDE_DIR_NAMES = {
    ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".git", ".claude", "dist", ".idea", ".vscode",
    "中期提交", "提交文档",
}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".egg-info")
# 含真实密钥，绝不能进压缩包
EXCLUDE_FILE_NAMES = {".env"}


def should_skip(path: Path) -> bool:
    if path.is_dir():
        if path.name in EXCLUDE_DIR_NAMES or path.name.endswith(EXCLUDE_SUFFIXES):
            return True
        return False
    if path.name in EXCLUDE_FILE_NAMES:
        return True
    return path.name.endswith(EXCLUDE_SUFFIXES)


def collect_files() -> list[Path]:
    files: list[Path] = []
    for current_dir, dir_names, file_names in os.walk(PROJECT_DIR):
        current = Path(current_dir)
        dir_names[:] = [d for d in dir_names if not should_skip(current / d)]
        for name in file_names:
            target = current / name
            if not should_skip(target):
                files.append(target)
    return sorted(files)


def human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} GB"


def main() -> None:
    parser = argparse.ArgumentParser(description="打包中期源码 ZIP")
    parser.add_argument("--out", default=str(PROJECT_DIR.parent / "中期提交" /
                                            "人工智能应用-学生前后端空骨架_中期源码.zip"))
    parser.add_argument("--list-only", action="store_true", help="只打印清单，不生成压缩包")
    args = parser.parse_args()

    files = collect_files()
    total_bytes = sum(path.stat().st_size for path in files)
    print(f"待打包文件 {len(files)} 个，合计 {human(total_bytes)}")
    print(f"排除：{', '.join(sorted(EXCLUDE_DIR_NAMES))}、*.pyc、*.egg-info、.env（含密钥）")

    if args.list_only:
        for path in files:
            print(f"  {path.relative_to(PROJECT_DIR)}")
        return

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, Path(ARCHIVE_ROOT) / path.relative_to(PROJECT_DIR))

    size = out_path.stat().st_size
    print(f"\n打包完成：{out_path}")
    print(f"压缩包大小：{human(size)}（原始 {human(total_bytes)}）")
    with zipfile.ZipFile(out_path) as archive:
        names = archive.namelist()
    print(f"包内条目：{len(names)} 个")
    print("顶层结构：")
    for item in sorted({n.split("/")[0] + ("/" + n.split("/")[1] if len(n.split("/")) > 1 else "")
                        for n in names}):
        print(f"  {item}")


if __name__ == "__main__":
    main()
