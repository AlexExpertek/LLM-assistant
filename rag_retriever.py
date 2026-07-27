from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class RagChunk:
    source: str
    text: str


class LocalTfidfRagRetriever:
    """Легкий MVP RAG без внешней vector DB.
    Для production можно заменить на Chroma/Qdrant/pgvector + embeddings.
    """

    def __init__(self, chunk_size_chars: int = 1800, chunk_overlap_chars: int = 250):
        self.chunk_size_chars = chunk_size_chars
        self.chunk_overlap_chars = chunk_overlap_chars
        self.chunks: list[RagChunk] = []
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), lowercase=True)
        self.matrix = None

    def _chunk_text(self, source: str, text: str) -> list[RagChunk]:
        chunks: list[RagChunk] = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size_chars, len(text))
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(RagChunk(source=source, text=chunk))
            if end == len(text):
                break
            start = max(0, end - self.chunk_overlap_chars)
        return chunks

    def build_from_dir(self, rag_dir: str | Path) -> None:
        all_chunks: list[RagChunk] = []
        for path in Path(rag_dir).glob("*.md"):
            text = path.read_text(encoding="utf-8")
            all_chunks.extend(self._chunk_text(path.name, text))
        self.chunks = all_chunks
        if not self.chunks:
            self.matrix = None
            return
        self.matrix = self.vectorizer.fit_transform([c.text for c in self.chunks])

    def retrieve(self, query: str, top_k: int = 6) -> list[str]:
        if self.matrix is None or not self.chunks:
            return []
        q = self.vectorizer.transform([query])
        scores = cosine_similarity(q, self.matrix).flatten()
        idxs = scores.argsort()[::-1][:top_k]
        result = []
        for i in idxs:
            if scores[i] <= 0:
                continue
            chunk = self.chunks[int(i)]
            result.append(f"Источник: {chunk.source}\n{chunk.text}")
        return result
