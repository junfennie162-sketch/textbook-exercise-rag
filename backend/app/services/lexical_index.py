"""混合检索稀疏路：内存 BM25 词法索引（中文 bigram + ASCII 词，零额外依赖）。"""
import math
import re
from collections import Counter
from typing import Iterable

_ASCII_WORD = re.compile(r"[a-zA-Z0-9]+")
_CJK_CHAR = re.compile(r"[一-鿿]")

K1 = 1.5  # Okapi BM25 词频饱和参数
B = 0.75  # 文档长度归一化参数


def tokenize(text: str) -> list[str]:
    """中文按 bigram 切分，英文/数字按整词切分，兼容数学表达式如 log2。"""
    tokens: list[str] = []
    for word in _ASCII_WORD.findall(text):
        tokens.append(word.lower())
    buffer = ""
    for ch in text:
        if _CJK_CHAR.match(ch):
            buffer += ch
        elif buffer:
            tokens.extend(_bigrams(buffer))
            buffer = ""
    if buffer:
        tokens.extend(_bigrams(buffer))
    return tokens


def _bigrams(word: str) -> list[str]:
    """单字成词，多字滑窗成二元组，保证单字查询也能命中。"""
    if len(word) == 1:
        return [word]
    return [word[i:i + 2] for i in range(len(word) - 1)]


class LexicalIndex:
    """进程内 BM25 索引：上传入库时增量添加，重启后首次检索从向量库懒加载。"""

    def __init__(self) -> None:
        self._docs: dict[str, dict] = {}  # chunk_id -> {"terms": Counter, "length": int, "item": dict}
        self._df: Counter = Counter()    # 词 -> 出现该词的文档数

    # ---- 索引维护 -------------------------------------------------
    def add_chunks(self, chunks: Iterable[dict]) -> int:
        added = 0
        for chunk in chunks:
            chunk_id = chunk["chunk_id"]
            if chunk_id in self._docs:
                continue
            terms = Counter(tokenize(chunk["text"]))
            self._docs[chunk_id] = {
                "terms": terms,
                "length": sum(terms.values()),
                "item": {
                    "chunk_id": chunk_id,
                    "text": chunk["text"],
                    "metadata": dict(chunk.get("metadata", {})),
                },
            }
            for term in terms:
                self._df[term] += 1
            added += 1
        return added

    def reset(self) -> None:
        self._docs.clear()
        self._df.clear()

    def remove_document(self, doc_id: str) -> int:
        """移除某文档的全部块并回收词频统计，返回移除块数。"""
        removed = [chunk_id for chunk_id, doc in self._docs.items()
                   if doc["item"]["metadata"].get("doc_id") == doc_id]
        for chunk_id in removed:
            doc = self._docs.pop(chunk_id)
            for term in doc["terms"]:
                self._df[term] -= 1
                if self._df[term] <= 0:
                    del self._df[term]
        return len(removed)

    def __len__(self) -> int:
        return len(self._docs)

    # ---- 检索 -----------------------------------------------------
    def search(self, query: str, top_k: int = 8,
               doc_type: str | None = None) -> list[dict]:
        """返回 [{chunk_id, text, metadata, bm25_score}]，按 BM25 得分降序。"""
        if not self._docs or not query.strip():
            return []
        n_docs = len(self._docs)
        avg_len = sum(d["length"] for d in self._docs.values()) / n_docs
        query_terms = tokenize(query)
        scored: list[tuple[float, dict]] = []
        for doc in self._docs.values():
            if doc_type and doc["item"]["metadata"].get("doc_type") != doc_type:
                continue
            score = 0.0
            for term in query_terms:
                tf = doc["terms"].get(term, 0)
                if not tf:
                    continue
                idf = math.log(1 + (n_docs - self._df[term] + 0.5) / (self._df[term] + 0.5))
                norm = 1 - B + B * doc["length"] / avg_len
                score += idf * tf * (K1 + 1) / (tf + K1 * norm)
            if score > 0:
                scored.append((score, doc["item"]))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [{**item, "bm25_score": round(score, 4)}
                for score, item in scored[:top_k]]


_INDEX: LexicalIndex | None = None


def get_lexical_index() -> LexicalIndex:
    """全局单例；冷启动时从向量库同步全量教材/习题块。"""
    global _INDEX
    if _INDEX is None:
        _INDEX = LexicalIndex()
        try:
            from app.services.vector_store import VectorStore
            _INDEX.add_chunks(VectorStore().list_chunks())
        except Exception:
            # 向量库不可用（如离线测试环境）时允许空索引启动
            pass
    return _INDEX


def reset_lexical_index() -> None:
    """测试用：清空单例，下一次 get 时重新懒加载。"""
    global _INDEX
    _INDEX = None
