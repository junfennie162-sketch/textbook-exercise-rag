"""读写 .env 配置：写入键值（一键部署脚本用）/ 检查配置有效性（--check）。

写入规则：已存在该键 → 替换该行；不存在 → 追加到末尾；其余行（含注释）原样保留。

检查规则（--check）：
  · 容忍并修复 UTF-8 BOM（记事本另存为 UTF-8 会带 BOM，会导致首个键读不到）；
  · 输出当前生效的通道 / 模型 / 是否已填 Key / 是否离线模式；
  · 退出码：0=可用；3=云端模式但 Key 为空（提醒）；1=文件缺失或无法解析。

用法：
    python scripts/apply_env_value.py LLM_MOCK true
    python scripts/apply_env_value.py LLM_PROVIDER ollama --env backend/.env
    python scripts/apply_env_value.py --check
"""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV = BASE_DIR / "backend" / ".env"

_TRUE_VALUES = ("1", "true", "yes", "on")
_BOM = b"\xef\xbb\xbf"


def apply_value(env_path: Path, key: str, value: str) -> bool:
    """写入键值；返回是否为"替换已有键"（False 表示追加了新键）。"""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    replaced = False
    output: list[str] = []
    for line in lines:
        if line.split("=")[0].strip() == key:
            output.append(f"{key}={value}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(f"{key}={value}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(output).rstrip("\n") + "\n", encoding="utf-8")
    return replaced


def _read_values(env_path: Path) -> dict[str, str]:
    """读取键值（顺手去掉 UTF-8 BOM，避免首个键名带 BOM 无法识别）。"""
    raw = env_path.read_bytes()
    if raw.startswith(_BOM):
        raw = raw[len(_BOM):]
        env_path.write_bytes(raw)
    values: dict[str, str] = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def inspect_env(env_path: Path) -> tuple[dict, int]:
    """检查配置并返回 (摘要, 退出码)。退出码 3 = 云端模式但未填 Key。"""
    if not env_path.exists():
        return {"exists": False}, 1
    values = _read_values(env_path)
    provider = values.get("LLM_PROVIDER", "cloud") or "cloud"
    mock = values.get("LLM_MOCK", "false").strip().lower() in _TRUE_VALUES
    summary = {
        "exists": True,
        "provider": provider,
        "model": values.get("LLM_MODEL", "") if provider == "cloud" else values.get("OLLAMA_MODEL", ""),
        "key_present": bool(values.get("LLM_API_KEY", "").strip()),
        "mock": mock,
    }
    if provider == "cloud" and not summary["key_present"] and not mock:
        return summary, 3
    return summary, 0


def _describe(summary: dict) -> str:
    if not summary.get("exists"):
        return "配置文件不存在"
    if summary["mock"]:
        return "离线演示模式（LLM_MOCK=true，不调用任何大模型）"
    if summary["provider"] == "ollama":
        return f"本地 Ollama 模式（模型：{summary['model'] or '未指定'}）"
    if summary["key_present"]:
        return f"云端 API 模式（模型：{summary['model'] or '未指定'}，Key 已填写）"
    return "云端 API 模式，但 LLM_API_KEY 为空——生成解析时会报鉴权错误"


def main() -> None:
    parser = argparse.ArgumentParser(description="写入或检查 .env 配置")
    parser.add_argument("key", nargs="?", help="配置键，如 LLM_MOCK（--check 时省略）")
    parser.add_argument("value", nargs="?", help="配置值，如 true（--check 时省略）")
    parser.add_argument("--env", default=str(DEFAULT_ENV), help=f"配置文件路径（默认 {DEFAULT_ENV}）")
    parser.add_argument("--check", action="store_true", help="检查配置有效性（不修改）")
    args = parser.parse_args()

    target = Path(args.env)

    if args.check:
        summary, code = inspect_env(target)
        print(f"[env] 配置检查：{_describe(summary)}")
        if code == 3:
            print("[env] 提示：可在记事本补填 LLM_API_KEY，或改用本地 Ollama / 离线模式")
        sys.exit(code)

    if not args.key or args.value is None:
        parser.error("写入模式需要提供 key 与 value（或用 --check）")

    replaced = apply_value(target, args.key, args.value)
    action = "已更新" if replaced else "已追加"
    print(f"[env] {action} {args.key}={args.value} -> {target}")
    sys.exit(0)


if __name__ == "__main__":
    main()

