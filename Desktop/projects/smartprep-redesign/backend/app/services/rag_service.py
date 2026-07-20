"""
SmartPrep AI - RAG Service
Uses sentence-transformers (free, local) for dense embeddings.
Hybrid retrieval: FAISS dense + BM25 sparse, reranked with a cross-encoder.
FAISS vector store provides per-session isolation.
"""
import json
import time
import numpy as np
from typing import List, Tuple, Optional, Set
from pathlib import Path

import faiss
from app.utils.config import settings
from app.utils.logger import setup_logger
from app.services.chunker import TextChunker

logger = setup_logger(__name__)

VECTOR_STORE_DIR = Path(settings.VECTOR_STORE_PATH)
VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)


class RAGService:
    def __init__(self):
        self.chunker = TextChunker(chunk_size=512, overlap=64)
        # BAAI/bge-small-en-v1.5 produces 384-dim embeddings (free, local, no API)
        self.embedding_dim = 384
        self._session_indices: dict = {}
        self._session_bm25: dict = {}          # BM25 index per session
        self._session_chunks: dict = {}        # chunk list per session (shared ref)
        self._indexed_doc_types: dict = {}
        self._embedder = None          # lazy-loaded on first use
        self._reranker = None          # lazy-loaded on first use
        self._retrieval_stats: dict = {}       # precision@k tracking

    def preload(self) -> None:
        """Explicitly warm the embedding model. Call from app startup to avoid cold-start latency."""
        self._get_embedder()

    def _get_embedder(self):
        """Load the local sentence-transformers model on first call."""
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
            self._embedder = SentenceTransformer(settings.EMBEDDING_MODEL)
            logger.info("Embedding model loaded")
        return self._embedder

    def _get_reranker(self):
        """Load the cross-encoder reranker on first call (lazy)."""
        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder
                logger.info("Loading cross-encoder reranker: cross-encoder/ms-marco-MiniLM-L-6-v2")
                self._reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
                logger.info("Cross-encoder reranker loaded")
            except Exception as e:
                logger.warning(f"Cross-encoder unavailable, reranking disabled: {e}")
                self._reranker = None
        return self._reranker

    def _get_bm25(self, session_id: str, chunks: List[str]):
        """Build or retrieve a BM25 index for the session's chunks."""
        if session_id not in self._session_bm25:
            try:
                from rank_bm25 import BM25Okapi
                tokenized = [c.lower().split() for c in chunks]
                self._session_bm25[session_id] = BM25Okapi(tokenized)
            except ImportError:
                logger.warning("rank_bm25 not installed — falling back to dense-only retrieval")
                self._session_bm25[session_id] = None
        return self._session_bm25[session_id]

    # ── Indexing ───────────────────────────────────────────────────────────────

    async def index_document(self, session_id: str, text: str, doc_type: str = "resume") -> int:
        already_indexed: Set[str] = self._indexed_doc_types.setdefault(session_id, set())
        if doc_type in already_indexed:
            logger.info(f"[{session_id}] Skipping duplicate index for {doc_type}")
            _, stored_chunks = self._load_or_create_index(session_id)
            return sum(1 for dt, _ in stored_chunks if dt == doc_type)

        chunks = self.chunker.chunk(text)
        logger.info(f"[{session_id}] Indexing {len(chunks)} chunks for {doc_type}")

        index, stored_chunks = self._load_or_create_index(session_id)

        tagged_texts = [f"[{doc_type.upper()}] {c}" for c in chunks]
        embeddings = self._embed_batch(tagged_texts)

        vectors = np.array(embeddings, dtype=np.float32)
        faiss.normalize_L2(vectors)
        index.add(vectors)

        stored_chunks.extend([(doc_type, c) for c in chunks])
        self._save_index(session_id, index, stored_chunks)
        self._session_indices[session_id] = (index, stored_chunks)
        already_indexed.add(doc_type)

        # Invalidate BM25 cache so it's rebuilt with new chunks
        self._session_bm25.pop(session_id, None)

        logger.info(f"[{session_id}] Index now has {index.ntotal} vectors")
        return len(chunks)

    async def index_job_description(self, session_id: str, jd_text: str) -> int:
        return await self.index_document(session_id, jd_text, doc_type="job_description")

    # ── Hybrid Retrieval ──────────────────────────────────────────────────────

    async def retrieve_hybrid(
        self,
        session_id: str,
        query: str,
        top_k: int = 5,
        doc_filter: Optional[str] = None,
    ) -> Tuple[str, float]:
        """
        Hybrid retrieval: dense (FAISS) + sparse (BM25), fused by reciprocal rank,
        then reranked with a cross-encoder.
        Returns (context_string, precision_at_k).
        """
        t0 = time.perf_counter()
        index, stored_chunks = self._load_or_create_index(session_id)

        if index.ntotal == 0:
            return "", 0.0

        chunk_texts = [c for _, c in stored_chunks]
        chunk_types = [dt for dt, _ in stored_chunks]

        # ── Dense retrieval ────────────────────────────────────────────────────
        candidate_k = min(top_k * 6, index.ntotal)
        query_emb = self._embed_single(query)
        query_vec = np.array([query_emb], dtype=np.float32)
        faiss.normalize_L2(query_vec)
        distances, faiss_indices = index.search(query_vec, candidate_k)

        dense_ranks: dict = {}  # idx → rank
        for rank, (score, idx) in enumerate(zip(distances[0], faiss_indices[0])):
            if idx == -1:
                continue
            if doc_filter and chunk_types[idx] != doc_filter:
                continue
            dense_ranks[idx] = rank

        # ── Sparse retrieval (BM25) ────────────────────────────────────────────
        sparse_ranks: dict = {}
        bm25 = self._get_bm25(session_id, chunk_texts)
        if bm25 is not None:
            tokenized_query = query.lower().split()
            bm25_scores = bm25.get_scores(tokenized_query)
            # Filter by doc_type, then rank
            filtered_pairs = [
                (i, s) for i, s in enumerate(bm25_scores)
                if (doc_filter is None or chunk_types[i] == doc_filter)
            ]
            filtered_pairs.sort(key=lambda x: x[1], reverse=True)
            for rank, (idx, _) in enumerate(filtered_pairs[:candidate_k]):
                sparse_ranks[idx] = rank

        # ── Reciprocal Rank Fusion (RRF) ───────────────────────────────────────
        k_rrf = 60
        all_indices = set(dense_ranks) | set(sparse_ranks)
        rrf_scores: dict = {}
        for idx in all_indices:
            score = 0.0
            if idx in dense_ranks:
                score += 1.0 / (k_rrf + dense_ranks[idx])
            if idx in sparse_ranks:
                score += 1.0 / (k_rrf + sparse_ranks[idx])
            rrf_scores[idx] = score

        # Take top (top_k * 3) candidates for reranking
        rerank_candidates = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_k * 3]

        # ── Cross-encoder Reranking ────────────────────────────────────────────
        reranker = self._get_reranker()
        if reranker and len(rerank_candidates) > 0:
            pairs = [(query, chunk_texts[idx]) for idx, _ in rerank_candidates]
            try:
                ce_scores = reranker.predict(pairs)
                reranked = sorted(
                    zip([idx for idx, _ in rerank_candidates], ce_scores),
                    key=lambda x: x[1], reverse=True
                )
            except Exception as e:
                logger.warning(f"Cross-encoder reranking failed, using RRF order: {e}")
                reranked = [(idx, score) for idx, score in rerank_candidates]
        else:
            reranked = [(idx, score) for idx, score in rerank_candidates]

        # ── Build context ──────────────────────────────────────────────────────
        results = []
        for idx, _ in reranked[:top_k]:
            dt = chunk_types[idx]
            results.append((dt, chunk_texts[idx]))

        context_parts = []
        for dt, text in results:
            label = "RESUME" if dt == "resume" else "JOB DESCRIPTION"
            context_parts.append(f"[{label}] {text}")

        # ── Precision@k (keyword overlap heuristic) ────────────────────────────
        query_tokens = set(query.lower().split())
        hit_count = sum(
            1 for _, text in results
            if any(tok in text.lower() for tok in query_tokens if len(tok) > 3)
        )
        precision_at_k = hit_count / len(results) if results else 0.0

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            f"[{session_id}] Hybrid retrieval: {len(results)} chunks, "
            f"precision@{top_k}={precision_at_k:.2f}, latency={elapsed_ms:.1f}ms"
        )

        # Track stats
        self._retrieval_stats[session_id] = {
            "last_precision_at_k": precision_at_k,
            "last_latency_ms": elapsed_ms,
            "top_k": top_k,
        }

        return "\n\n".join(context_parts), precision_at_k

    # ── Legacy dense-only retrieval (kept for backward compat) ────────────────

    async def retrieve(
        self,
        session_id: str,
        query: str,
        top_k: int = 5,
        doc_filter: Optional[str] = None,
    ) -> str:
        """Dense-only retrieval. Prefer retrieve_hybrid() for production use."""
        context, _ = await self.retrieve_hybrid(session_id, query, top_k, doc_filter)
        return context

    async def retrieve_for_questions(self, session_id: str, job_description: str) -> str:
        resume_ctx, _ = await self.retrieve_hybrid(
            session_id, job_description, top_k=6, doc_filter="resume"
        )
        jd_ctx, _ = await self.retrieve_hybrid(
            session_id, "key requirements skills experience", top_k=3, doc_filter="job_description"
        )
        return f"{resume_ctx}\n\n{jd_ctx}".strip()

    async def retrieve_for_evaluation(
        self,
        session_id: str,
        query: str,
        extra_queries: Optional[List[str]] = None,
    ) -> Tuple[str, float]:
        """
        Retrieve resume context for answer evaluation.
        Supports multi-query retrieval from rewritten queries.
        Returns (context, avg_precision).
        """
        queries = [query]
        if extra_queries:
            queries.extend(extra_queries)

        all_chunks = []
        precisions = []
        seen_texts: Set[str] = set()

        for q in queries[:3]:  # max 3 queries
            ctx, prec = await self.retrieve_hybrid(session_id, q, top_k=4, doc_filter="resume")
            precisions.append(prec)
            for chunk in ctx.split("\n\n"):
                if chunk and chunk not in seen_texts:
                    seen_texts.add(chunk)
                    all_chunks.append(chunk)

        avg_precision = sum(precisions) / len(precisions) if precisions else 0.0
        return "\n\n".join(all_chunks[:8]), avg_precision

    # ── Embeddings (local, free) ────────────────────────────────────────────────

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts using the local sentence-transformers model."""
        embedder = self._get_embedder()
        vectors = embedder.encode(texts, show_progress_bar=False, convert_to_numpy=True)
        return vectors.tolist()

    def _embed_single(self, text: str) -> List[float]:
        embedder = self._get_embedder()
        vector = embedder.encode([text], show_progress_bar=False, convert_to_numpy=True)
        return vector[0].tolist()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_or_create_index(self, session_id: str) -> Tuple[faiss.Index, List]:
        if session_id in self._session_indices:
            return self._session_indices[session_id]

        index_path = VECTOR_STORE_DIR / f"{session_id}.faiss"
        chunks_path = VECTOR_STORE_DIR / f"{session_id}.chunks.json"

        if index_path.exists() and chunks_path.exists():
            index = faiss.read_index(str(index_path))
            stored_chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
            self._indexed_doc_types.setdefault(session_id, set()).update(
                dt for dt, _ in stored_chunks
            )
            logger.info(f"[{session_id}] Loaded index from disk ({index.ntotal} vectors)")
        else:
            index = faiss.IndexFlatIP(self.embedding_dim)
            stored_chunks = []
            logger.info(f"[{session_id}] Created new FAISS index")

        self._session_indices[session_id] = (index, stored_chunks)
        return index, stored_chunks

    def _save_index(self, session_id: str, index: faiss.Index, chunks: List):
        faiss.write_index(index, str(VECTOR_STORE_DIR / f"{session_id}.faiss"))
        chunks_path = VECTOR_STORE_DIR / f"{session_id}.chunks.json"
        chunks_path.write_text(json.dumps(chunks), encoding="utf-8")

    def session_exists(self, session_id: str) -> bool:
        if session_id in self._session_indices:
            return True
        return (VECTOR_STORE_DIR / f"{session_id}.faiss").exists()

    def cleanup_session(self, session_id: str):
        self._session_indices.pop(session_id, None)
        self._indexed_doc_types.pop(session_id, None)
        self._session_bm25.pop(session_id, None)
        self._retrieval_stats.pop(session_id, None)
        for suffix in [".faiss", ".chunks.json"]:
            p = VECTOR_STORE_DIR / f"{session_id}{suffix}"
            if p.exists():
                p.unlink()

    def get_retrieval_stats(self, session_id: str) -> dict:
        return self._retrieval_stats.get(session_id, {})


rag_service = RAGService()
