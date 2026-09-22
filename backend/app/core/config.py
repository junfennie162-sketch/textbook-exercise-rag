from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.runtime_settings import RuntimeJsonSource, runtime_path

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "教材习题解析生成器"
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 运行期数据目录（上传文件、页段、数据库、解析结果）；可用 DATA_DIR 覆盖
    data_dir: Path = BASE_DIR / "data"

    # ==================== LLM 大语言模型配置（双通道） ====================
    # 两种连接模型的方式，由 LLM_PROVIDER 一键切换（参照 rag_law 模板的切换设计）：
    #   cloud  云端 API —— OpenAI 兼容端点（智谱 GLM / DeepSeek 等），需联网与 API Key
    #   ollama 本地模型 —— 本地 Ollama 服务（OpenAI 兼容 :11434/v1），零费用、断网可用
    # 两条通道统一走 OpenAI 兼容协议（core/llm.py），上层调用代码完全无感。
    llm_provider: Literal["cloud", "ollama"] = "cloud"

    # 方式一：云端 API（OpenAI 兼容端点；换 DeepSeek 时改 base_url 为
    # https://api.deepseek.com、model 为 deepseek-chat，Key 填 DEEPSEEK 的即可）
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_api_key: str = ""
    llm_model: str = "glm-4.6"
    llm_temperature: float = 0.3
    llm_top_p: float = 1.0            # 核采样；1.0 = 不截断
    llm_max_tokens: int = 4096        # 单次生成上限（含推理型模型的思考额度）
    custom_instruction: str = ""      # 附加指令：只追加到提示词末尾，不覆盖底线规则

    # 方式二：本地 Ollama（api_key 仅为占位，Ollama 不校验；模型需先 ollama pull）
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:3b"
    ollama_api_key: str = "ollama"

    # 离线模板模式（优先级最高）：不访问任何外部服务，用检索片段拼装五段式解析
    llm_mock: bool = False

    # Retrieval / RAG
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    retrieval_top_k: int = 4
    similarity_threshold: float = 0.60
    # 来源相对筛选：低于「最高相似度 × 该值」的块不作为依据（1.0 或 0 = 关闭筛选）
    evidence_relative_cut: float = 0.85

    # Hybrid retrieval (加分项：BM25+向量混合召回、RRF 融合、轻量重排)
    retrieval_mode: str = "hybrid"     # hybrid | vector（消融实验对照用）
    rerank_enabled: bool = True        # 轻量重排开关（消融实验对照用）
    recall_multiplier: int = 3         # 每路召回量 = top_k × multiplier
    rrf_k: int = 60                    # RRF 倒数排名融合常数
    rerank_alpha: float = 0.6          # 重排权重：α×余弦 + (1-α)×关键词覆盖度

    # Chunking (2.1)
    chunk_max_size: int = 600
    chunk_overlap: int = 80

    # Upload
    max_upload_mb: int = 20

    # Batch (4.1 批量解析：并发度限流 + 规模上限，避免把模型接口打满)
    batch_concurrency: int = 3
    batch_max_questions: int = 100   # 单次批量题目数上限
    batch_max_jobs: int = 3          # 同时运行的批量任务数上限

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings,
                                   dotenv_settings, file_secret_settings):
        """配置优先级：显式传参 > runtime_settings.json（设置面板覆盖）> .env > 默认值。

        设置面板保存后调用方执行 get_settings.cache_clear()，全项目热生效、免重启。
        """
        return (init_settings, RuntimeJsonSource(settings_cls, runtime_path()),
                env_settings, dotenv_settings, file_secret_settings)

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def solutions_dir(self) -> Path:
        return self.data_dir / "solutions"

    @property
    def samples_dir(self) -> Path:
        # 样例文档在项目根的 data/samples（BASE_DIR 指向 backend）
        return BASE_DIR.parent / "data" / "samples"

    @property
    def chroma_dir(self) -> Path:
        return BASE_DIR / "chroma_db"

    @property
    def models_cache_dir(self) -> Path:
        return BASE_DIR / "models_cache"

    @property
    def reports_dir(self) -> Path:
        return BASE_DIR / "reports"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    def llm_mode(self) -> str:
        """当前生成模式（全项目唯一口径）：mock > ollama > cloud。

        落库的 solutions.mode、/api/health 与评测报告的 mode 字段均取自此函数；
        历史记录中的旧值 "live" 由前端映射为云端。
        """
        if self.llm_mock:
            return "mock"
        return self.llm_provider

    def llm_active_model(self) -> str:
        """当前实际使用的模型名（云端或 Ollama），供状态展示与日志使用；mock 无模型。"""
        if self.llm_mode() == "mock":
            return ""
        if self.llm_mode() == "ollama":
            return self.ollama_model
        return self.llm_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
