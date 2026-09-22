"""2.2 向量化与向量数据库（fastembed + Chroma 持久化）。"""
import chromadb
from fastembed import TextEmbedding

from app.core.config import Settings, get_settings

_COLLECTION = "textbook_chunks"


class VectorStore:
    def __init__(self, settings: Settings | None = None, ephemeral: bool = False):
        self.settings = settings or get_settings()
        # 嵌入模型懒加载：只读操作（按 ID 查块、列块、删除）不需要模型，
        # 避免每次调用都初始化 ONNX 会话（秒级开销）
        self._model = None
        if ephemeral:
            client = chromadb.EphemeralClient(
                settings=chromadb.Settings(anonymized_telemetry=False))
        else:
            client = chromadb.PersistentClient(
                path=str(self.settings.chroma_dir),
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
        self.collection = client.get_or_create_collection(
            name=_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def model(self) -> TextEmbedding:
        if self._model is None:
            self._model = TextEmbedding(
                model_name=self.settings.embedding_model,
                cache_dir=str(self.settings.models_cache_dir),
            )
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self.model.embed(texts)]

    def add_chunks(self, chunks: list[dict]) -> int:
        if not chunks:
            return 0
        texts = [c["text"] for c in chunks]
        self.collection.add(
            ids=[c["chunk_id"] for c in chunks],
            embeddings=self.embed(texts),
            documents=texts,
            metadatas=[c["metadata"] for c in chunks],
        )
        return len(chunks)

    def query(self, text: str, top_k: int | None = None,
              where: dict | None = None) -> list[dict]:
        """返回 [{chunk_id, text, metadata, score}]，score 为余弦相似度（越大越相似）。"""
        k = top_k or self.settings.retrieval_top_k
        k = min(k, max(self.collection.count(), 1))
        if self.collection.count() == 0:
            return []
        result = self.collection.query(
            query_embeddings=self.embed([text]),
            n_results=k,
            where=where,
        )
        items: list[dict] = []
        for chunk_id, doc, meta, dist in zip(
            result["ids"][0],
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        ):
            items.append({
                "chunk_id": chunk_id,
                "text": doc,
                "metadata": meta,
                "score": round(1.0 - float(dist), 4),
            })
        return items

    def get(self, chunk_id: str) -> dict | None:
        result = self.collection.get(ids=[chunk_id])
        if not result["ids"]:
            return None
        return {
            "chunk_id": result["ids"][0],
            "text": result["documents"][0],
            "metadata": result["metadatas"][0],
        }

    def list_chunks(self, where: dict | None = None) -> list[dict]:
        """全量拉取块（含元数据），供 BM25 词法索引冷启动同步。"""
        result = self.collection.get(where=where, include=["documents", "metadatas"])
        return [
            {"chunk_id": chunk_id, "text": doc, "metadata": meta or {}}
            for chunk_id, doc, meta in zip(result["ids"], result["documents"],
                                           result["metadatas"])
        ]

    def count(self) -> int:
        return self.collection.count()

    def delete_document(self, doc_id: str) -> int:
        """删除某文档的全部知识块，返回删除块数（知识库清理用）。"""
        before = self.collection.count()
        self.collection.delete(where={"doc_id": doc_id})
        return before - self.collection.count()
