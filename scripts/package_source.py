"""打包源码 ZIP：排除依赖目录与含密钥的配置，保留可离线运行的模型与示例数据。

用法（项目根目录下）：
    python scripts/package_source.py
    python scripts/package_source.py --out "D:/提交/源码包.zip"
    python scripts/package_source.py --list-only     # 只打印将要打包的清单，不生成文件

打包规则：
  · 排除：虚拟环境、node_modules、__pycache__、.pytest_cache、*.egg-info、dist、.git、.claude、
          其他提交物目录、**所有含真实密钥的 .env 系列文件**（.env / .env.bak* / .env.local 等），
          以及 HF 缓存的内容库 backend/models_cache/models--*/blobs/（snapshots/ 已是同一份内容，
          存两遍会让包白胖一倍）
  · 保留：全部源码、README、.env.example（配置样例）、示例数据、评测报告、
          本地嵌入模型快照（models_cache/snapshots，约 95MB，保证解压后无需联网即可运行）
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

# 模型快照载荷的最小体积（bge-small-zh-v1.5 的 onnx 约 95MB，留足余量即可判定完整）
MIN_MODEL_PAYLOAD_BYTES = 1_000_000


def is_hf_blob_dir(path: Path) -> bool:
    """是否为 HF 缓存的内容库目录（models_cache/models--*/blobs/）。

    HF 缓存把正文存在 blobs/，snapshots/ 里是同一份内容的硬链接/副本；
    若两者都打包，同一个 95MB 模型会在包里存两遍。离线加载只走 snapshots/ 路径
    （已实测：仅 snapshots 的包 HF_HUB_OFFLINE=1 下可正常加载），故跳过 blobs/。
    """
    return (path.name == "blobs"
            and path.parent.name.startswith("models--")
            and "models_cache" in path.parts)


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
        return is_hf_blob_dir(path)
    if _is_secret_file(path.name):
        return True
    return path.name.endswith(EXCLUDE_SUFFIXES)


def check_model_cache(files: list[Path]) -> None:
    """自检：排除 blobs/ 后，snapshots/ 里必须留有完整的模型载荷。

    历史上出现过缓存目录只有空壳（blobs 尚未落盘）的情况，那样的包解压后无法离线运行，
    因此出包前先把关，避免打出"看着有模型、实际加载失败"的包。
    """
    cache_files = [p for p in files if "models_cache" in p.parts]
    if not cache_files:
        return  # 树里没带模型缓存：README 已说明克隆后的获取方式，不改判
    payloads = [p for p in cache_files if "snapshots" in p.parts]
    if not payloads:
        raise SystemExit("[严重] models_cache 内没有 snapshots/ 快照文件，"
                         "打出的包无法离线加载模型，请先用完整缓存替换后重试！")
    biggest = max(p.stat().st_size for p in payloads)
    if biggest < MIN_MODEL_PAYLOAD_BYTES:
        raise SystemExit(f"[严重] models_cache/snapshots 内最大文件仅 {human(biggest)}，"
                         "模型载荷不完整（可能只有符号链接或空壳），打包前请先补齐缓存！")


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
    check_model_cache(files)
    total_bytes = sum(path.stat().st_size for path in files)
    print(f"待打包文件 {len(files)} 个，合计 {human(total_bytes)}")
    print("排除：虚拟环境/node_modules/__pycache__/.git 等目录、*.pyc、全部 .env 系列密钥文件、"
          "模型缓存的 blobs 副本目录")
    print("（.env.example 配置样例与模型快照保留）")

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
