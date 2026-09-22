"""打包源码 ZIP：排除依赖目录与含密钥的配置，保留可离线运行的模型与示例数据。

用法（项目根目录下）：
    python scripts/package_source.py
    python scripts/package_source.py --out "D:/提交/源码包.zip"
    python scripts/package_source.py --list-only     # 只打印将要打包的清单，不生成文件

打包规则：
  · 排除：虚拟环境、node_modules、__pycache__、.pytest_cache、*.egg-info、dist、.git、.claude、
          其他提交物目录，以及**所有含真实密钥的 .env 系列文件**（.env / .env.bak* / .env.local 等）
  · 保留：全部源码、README、.env.example（配置样例）、示例数据（data/samples）、评测报告、
          本地嵌入模型（models_cache，约 95MB，保证解压后无需联网即可运行）
"""
import argparse
import os
import time
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BASE_DIR  # 以项目根目录（含 backend/frontend）为打包根
ARCHIVE_ROOT = PROJECT_DIR.name

EXCLUDE_DIR_NAMES = {
    ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".git", ".claude", "dist", ".idea", ".vscode",
    "中期提交", "提交文档", "最终提交",
}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".egg-info")


def _is_secret_file(name: str) -> bool:
    """含密钥的配置文件一律排除：.env / .env.bak* / .env.local / runtime_settings.json。

    runtime_settings.json 是"模型设置"面板保存的覆盖值文件（可能含 API Key），
    真实配置一律排除，只放行 .env.example（配置样例）。
    """
    if name == ".env.example":
        return False
    if name == "runtime_settings.json":
        return True
    return name == ".env" or name.startswith(".env.")


def should_skip(path: Path) -> bool:
    if path.is_dir():
        if path.name in EXCLUDE_DIR_NAMES or path.name.endswith(EXCLUDE_SUFFIXES):
            return True
        return False
    if _is_secret_file(path.name):
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
    parser = argparse.ArgumentParser(description="打包源码 ZIP（自动排除含密钥的 .env 系列文件）")
    parser.add_argument("--out", default=str(PROJECT_DIR.parent / "最终提交" /
                                            f"人工智能应用-学生前后端空骨架_最终源码_{time.strftime('%Y%m%d')}.zip"))
    parser.add_argument("--list-only", action="store_true", help="只打印清单，不生成压缩包")
    args = parser.parse_args()

    files = collect_files()
    total_bytes = sum(path.stat().st_size for path in files)
    print(f"待打包文件 {len(files)} 个，合计 {human(total_bytes)}")
    print("排除：虚拟环境/node_modules/__pycache__/.git 等目录、*.pyc、以及全部 .env 系列密钥文件")
    print("（.env.example 配置样例保留）")

    if args.list_only:
        for path in files:
            print(f"  {path.relative_to(PROJECT_DIR)}")
        return

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 硬链接去重：同一份数据只压一次。HF 缓存里 blobs 与 snapshots 是硬链接关系，
    # 加载时读的是 snapshots 路径 —— 去重必须优先保留非 blobs 的那份，否则包解压后加载不到模型。
    chosen_by_inode: dict[tuple[int, int], Path] = {}
    for path in files:
        stat = path.stat()
        inode = (stat.st_dev, stat.st_ino)
        current = chosen_by_inode.get(inode)
        if current is None:
            chosen_by_inode[inode] = path
        elif "/blobs/" in current.as_posix() and "/blobs/" not in path.as_posix():
            chosen_by_inode[inode] = path
    chosen = set(chosen_by_inode.values())
    skipped = [path for path in files if path not in chosen]

    written_bytes = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            if path not in chosen:
                continue
            written_bytes += path.stat().st_size
            archive.write(path, Path(ARCHIVE_ROOT) / path.relative_to(PROJECT_DIR))

    size = out_path.stat().st_size
    print(f"\n打包完成：{out_path}")
    print(f"压缩包大小：{human(size)}（实际写入 {human(written_bytes)}"
          + (f"，硬链接去重跳过 {len(skipped)} 个重复文件" if skipped else "") + "）")
    with zipfile.ZipFile(out_path) as archive:
        names = archive.namelist()
    print(f"包内条目：{len(names)} 个")

    # 出包前自检：包内不得出现任何真实密钥文件
    leaked = [n for n in names
              if Path(n).name == "runtime_settings.json"
              or Path(n).name == ".env"
              or (Path(n).name.startswith(".env.") and Path(n).name != ".env.example")]
    if leaked:
        raise SystemExit(f"[严重] 压缩包内发现密钥文件：{leaked}，请立即删除该压缩包并检查排除规则！")
    print("密钥自检：包内无 .env / runtime_settings.json（仅保留 .env.example）✓")

    print("顶层结构：")
    for item in sorted({n.split("/")[0] + ("/" + n.split("/")[1] if len(n.split("/")) > 1 else "")
                        for n in names}):
        print(f"  {item}")


if __name__ == "__main__":
    main()
