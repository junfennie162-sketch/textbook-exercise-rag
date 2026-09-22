"""运行期可调参数：规格表 + 覆盖值持久化（最高优先级配置源）。

设计要点（借鉴"参数面板"思路，实现完全自研）：
- `SETTINGS_SPEC` 是唯一真源：后端把它下发给前端渲染控件，保存时按同一份规格做
  白名单与范围截断——新增参数只改这一处，前后端同时生效；
- 覆盖值独立存 `runtime_settings.json`（**不写回 .env**，避免破坏注释与版本管理），
  优先级：显式传参 > runtime_settings.json > .env > 代码默认值；
- 保存后由调用方执行 `get_settings.cache_clear()`，全项目**热生效、免重启**；
- 该文件可能含 API Key，属敏感文件：.gitignore 与打包脚本均已排除并自检。

接口层请使用 `app/api/settings.py`，本模块只负责数据与规则。
"""
import json
import os
from pathlib import Path

from pydantic_settings import PydanticBaseSettingsSource

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RUNTIME_FILE_NAME = "runtime_settings.json"
KEY_FIELD = "llm_api_key"           # 掩码回显的字段
_MASK_CHAR = "•"

# ==================== 可调参数规格表（唯一真源） ====================
# type: number（可带 min/max/step/integer）| bool | select | text | password | textarea
SETTINGS_SPEC: list[dict] = [
    {
        "key": "llm_provider", "group": "模型通道", "label": "模型通道", "type": "select",
        "options": ["cloud", "ollama"],
        "hint": "cloud=云端 API（OpenAI 兼容）；ollama=本地模型。切换后立即热生效",
    },
    {
        "key": "llm_base_url", "group": "模型通道", "label": "云端 Base URL", "type": "text",
        "max_length": 200, "hint": "OpenAI 兼容端点，需带服务商要求的路径（如 /v1、/api/paas/v4）",
    },
    {
        "key": "llm_model", "group": "模型通道", "label": "云端模型名", "type": "text",
        "max_length": 120, "hint": "必须与端点实际可用模型一致；点「测试连接」可查看模型列表",
    },
    {
        "key": KEY_FIELD, "group": "模型通道", "label": "云端 API Key", "type": "password",
        "max_length": 200, "hint": "只回显尾 4 位；留空或保持掩码表示不修改",
    },
    {
        "key": "ollama_base_url", "group": "模型通道", "label": "Ollama 地址", "type": "text",
        "max_length": 200, "hint": "本地 Ollama 的 OpenAI 兼容地址（默认 11434 端口）",
    },
    {
        "key": "ollama_model", "group": "模型通道", "label": "Ollama 模型名", "type": "text",
        "max_length": 120, "hint": "需先用 ollama pull 拉取，如 qwen2.5:3b",
    },
    {
        "key": "llm_temperature", "group": "推理参数", "label": "采样温度 temperature", "type": "number",
        "min": 0, "max": 2, "step": 0.05, "hint": "越低输出越确定；教学解析建议 0.2~0.5",
    },
    {
        "key": "llm_top_p", "group": "推理参数", "label": "核采样 top_p", "type": "number",
        "min": 0.05, "max": 1, "step": 0.05, "hint": "1.0 表示不启用截断（默认）",
    },
    {
        "key": "llm_max_tokens", "group": "推理参数", "label": "最大生成长度 max_tokens", "type": "number",
        "min": 512, "max": 16384, "step": 256, "integer": True,
        "hint": "推理型模型思考也占额度，建议 ≥4096",
    },
    {
        "key": "retrieval_top_k", "group": "检索参数", "label": "检索条数 top_k", "type": "number",
        "min": 1, "max": 10, "step": 1, "integer": True, "hint": "默认 4；提高可增覆盖但上下文更长",
    },
    {
        "key": "similarity_threshold", "group": "检索参数", "label": "相似度门控阈值", "type": "number",
        "min": 0.3, "max": 0.9, "step": 0.01, "hint": "低于该值判为无依据并拒答（默认 0.60）",
    },
    {
        "key": "evidence_relative_cut", "group": "检索参数", "label": "来源相对筛选阈值", "type": "number",
        "min": 0, "max": 1, "step": 0.05,
        "hint": "低于「最高分×该值」的来源不进入解析与引用列表（默认 0.85；1.0 或 0 = 关闭）",
    },
    {
        "key": "rerank_enabled", "group": "检索参数", "label": "启用轻量重排", "type": "bool",
        "hint": "α×向量余弦 + (1-α)×关键词覆盖度",
    },
    {
        "key": "rerank_alpha", "group": "检索参数", "label": "重排权重 α", "type": "number",
        "min": 0, "max": 1, "step": 0.05, "hint": "α 越大越依赖向量相似度",
    },
    {
        "key": "recall_multiplier", "group": "检索参数", "label": "每路召回倍数", "type": "number",
        "min": 1, "max": 8, "step": 1, "integer": True, "hint": "向量/BM25 各召回 top_k × 该倍数后融合",
    },
    {
        "key": "batch_concurrency", "group": "运行参数", "label": "批量并发度", "type": "number",
        "min": 1, "max": 8, "step": 1, "integer": True, "hint": "设为 1 即串行；接口限流时降为 1",
    },
    {
        "key": "custom_instruction", "group": "附加指令", "label": "附加指令（追加到提示词末尾）", "type": "textarea",
        "max_length": 500,
        "hint": "只追加、不覆盖底线提示词：必须给出依据、无依据必须拒答等规则不可改写",
    },
]

_SPEC_BY_KEY = {item["key"]: item for item in SETTINGS_SPEC}


def runtime_path(data_dir: Path | None = None) -> Path:
    """覆盖值文件路径：随 DATA_DIR（与数据库/上传文件同目录）。"""
    base = data_dir or Path(os.environ.get("DATA_DIR") or DEFAULT_DATA_DIR)
    return base / RUNTIME_FILE_NAME


def load_overrides(path: Path | None = None) -> dict:
    """读取覆盖值；文件缺失或损坏时按"无覆盖"处理，绝不阻断启动。"""
    target = path or runtime_path()
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def is_masked(value) -> bool:
    """判断提交上来的 Key 是否为掩码回显（掩码或空值都表示"不修改"）。"""
    return not isinstance(value, str) or not value.strip() or _MASK_CHAR in value


def mask_key(value: str | None) -> str:
    """Key 掩码回显：只露尾 4 位。"""
    if not value:
        return ""
    return f"{_MASK_CHAR * 4}{value[-4:]}" if len(value) > 4 else _MASK_CHAR * 4


def _sanitize_value(spec: dict, value):
    """按规格做类型转换与范围截断；无法处理时返回 None（调用方跳过该键）。"""
    kind = spec["type"]
    if kind == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if spec.get("min") is not None:
            number = max(float(spec["min"]), number)
        if spec.get("max") is not None:
            number = min(float(spec["max"]), number)
        return int(number) if spec.get("integer") else round(number, 4)
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if kind == "select":
        text = str(value).strip()
        return text if text in spec.get("options", []) else None
    if kind in ("text", "password", "textarea"):
        text = str(value).strip()
        if len(text) > spec.get("max_length", 300):
            return None
        return text
    return None


def sanitize_updates(updates: dict) -> tuple[dict, list[str]]:
    """白名单 + 截断：返回 (可保存的更新, 被拒绝的键列表)。

    未知键直接拒绝（不写盘）；Key 为掩码/空值表示"不修改"，从更新中剔除。
    """
    accepted: dict = {}
    rejected: list[str] = []
    for key, value in (updates or {}).items():
        spec = _SPEC_BY_KEY.get(key)
        if spec is None:
            rejected.append(key)
            continue
        if key == KEY_FIELD and is_masked(value):
            continue
        cleaned = _sanitize_value(spec, value)
        if cleaned is None:
            rejected.append(key)
            continue
        accepted[key] = cleaned
    return accepted, rejected


def apply_overrides(updates: dict, path: Path | None = None) -> tuple[dict, list[str]]:
    """合并保存覆盖值（白名单 + 截断），返回 (实际写入的更新, 被拒绝的键)。"""
    target = path or runtime_path()
    accepted, rejected = sanitize_updates(updates)
    merged = {**load_overrides(target), **accepted}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return accepted, rejected


def reset_overrides(path: Path | None = None) -> None:
    """清空全部覆盖值，恢复 .env / 默认配置。"""
    target = path or runtime_path()
    target.unlink(missing_ok=True)


class RuntimeJsonSource(PydanticBaseSettingsSource):
    """pydantic-settings 自定义配置源：runtime_settings.json（设置面板保存的覆盖值）。

    在 Settings 的 `settings_customise_sources` 中排在 .env 之前，
    从而形成"显式传参 > JSON 覆盖 > .env > 默认值"的优先级。
    """

    def __init__(self, settings_cls, path: Path):
        super().__init__(settings_cls)
        self.path = path

    def get_field_value(self, field, field_name):  # 抽象方法：整表在 __call__ 里返回
        return None, field_name, False

    def __call__(self) -> dict:
        return load_overrides(self.path)
