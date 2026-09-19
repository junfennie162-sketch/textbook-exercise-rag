from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "教材习题解析生成器"
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # 运行期数据目录（上传文件、页段、数据库、解析结果）；可用 DATA_DIR 覆盖
    data_dir: Path = BASE_DIR / "data"

    # LLM (Anthropic-compatible endpoint)
    llm_base_url: str = "https://open.bigmodel.cn/api/anthropic"
    llm_api_key: str = ""
    llm_model: str = "glm-4.6"
    llm_temperature: float = 0.3
    llm_mock: bool = False

    # Retrieval / RAG
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    retrieval_top_k: int = 4
    similarity_threshold: float = 0.45

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

    # Batch (4.1 批量解析：并发度限流，避免把模型接口打满)
    batch_concurrency: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
