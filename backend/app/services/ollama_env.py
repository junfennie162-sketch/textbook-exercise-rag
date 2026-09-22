"""本地 Ollama 环境探测：区分"未安装 / 已安装未启动 / 运行中"。

用途：让 /api/llm/status 与模型拉取接口给出**精确**的排查提示——
「没安装」和「装了没启动」的处理方式完全不同（下载安装 vs 打开托盘程序）。
只做本地文件/进程探测，不发起网络请求（运行状态由调用方按需探测）。
"""
import shutil
from pathlib import Path

# 各平台常见安装位置（PATH 里找不到时的兜底探测）
_DEFAULT_PATHS = (
    # Windows：官方安装器默认的用户级安装目录
    Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
    # macOS
    Path("/Applications/Ollama.app"),
    # Linux 常见路径
    Path("/usr/local/bin/ollama"),
    Path("/usr/bin/ollama"),
    Path("/snap/bin/ollama"),
)

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"


def ollama_binary() -> str | None:
    """返回 ollama 可执行文件路径；未安装时返回 None。"""
    found = shutil.which("ollama")
    if found:
        return found
    for path in _DEFAULT_PATHS:
        if path.exists():
            return str(path)
    return None


def ollama_installed() -> bool:
    """本机是否安装了 Ollama（不代表服务已启动）。"""
    return ollama_binary() is not None


def ollama_failure_hint(model: str) -> str:
    """连不上本地 Ollama 时给出分场景提示（已装未启动 / 未安装）。"""
    if ollama_installed():
        return (f"已检测到 Ollama 安装但服务未响应：请启动 Ollama（开始菜单或托盘图标）后重试；"
                f"若模型尚未下载，执行 ollama pull {model}")
    return (f"未检测到本地 Ollama：请先安装（{OLLAMA_DOWNLOAD_URL}），或在网页「模型设置」面板"
            f"切换到云端 / 离线模式；安装完成后可在该面板一键拉取模型")
