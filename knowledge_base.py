"""
Knowledge Base — Parses me.txt, embeds via Pinecone, stores/queries via Pinecone.
"""

import os
import re
import json
import logging
import time
from dataclasses import dataclass, field
from pinecone import Pinecone, ServerlessSpec

from config import get_settings

logger = logging.getLogger(__name__)


# ── Data Classes ────────────────────────────────────────────────

@dataclass
class Chunk:
    """A single chunk of knowledge from me.txt."""
    section: str
    chunk_index: int
    text: str
    token_count: int = 0
    embedding: list[float] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.section.lower().replace(' ', '-')}_{self.chunk_index}"


# ── Parsing ─────────────────────────────────────────────────────

def parse_me_txt(path: str) -> list[Chunk]:
    """Parse me.txt into section-based chunks with metadata."""
    if not os.path.exists(path):
        logger.warning(f"me.txt not found at {path}")
        return []

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Support both === SECTION === and --- SECTION --- patterns
    section_pattern = r"(?:===|---)\s*(.+?)\s*(?:===|---)"
    parts = re.split(section_pattern, content)

    chunks: list[Chunk] = []
    # parts[0] is text before first section (usually empty)
    # parts[1], parts[2] = section_name, section_content, ...
    for i in range(1, len(parts), 2):
        section_name = parts[i].strip().upper()
        section_content = parts[i + 1].strip() if i + 1 < len(parts) else ""

        if not section_content:
            continue

        # Split into sub-chunks if content is long (≤512 tokens ≈ ~2000 chars)
        sub_chunks = _split_into_chunks(section_content, max_chars=1800)

        for idx, text in enumerate(sub_chunks):
            token_count = len(text.split())  # Rough token estimate
            chunks.append(Chunk(
                section=section_name,
                chunk_index=idx,
                text=text,
                token_count=token_count,
            ))

    logger.info(f"Parsed {len(chunks)} chunks from {path}")
    return chunks


def _split_into_chunks(text: str, max_chars: int = 1800) -> list[str]:
    """Split text into chunks at paragraph boundaries."""
    if len(text) <= max_chars:
        return [text]

    paragraphs = text.split("\n\n")
    chunks = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chars and current:
            chunks.append(current.strip())
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text]


# ── Embedding ───────────────────────────────────────────────────

def _pinecone_embed(texts: list[str], input_type: str = "passage") -> list[list[float]]:
    settings = get_settings()
    pc = Pinecone(api_key=settings.pinecone_api_key)
    
    # Pinecone inference requires input_type: "passage" for docs, "query" for queries
    embeddings_data = pc.inference.embed(
        model=settings.embedding_model,
        inputs=texts,
        parameters={"input_type": input_type, "truncate": "END"}
    )
    
    # Extract the vector values
    return [record["values"] for record in embeddings_data.data]

def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts using Pinecone Serverless Inference API."""
    embeddings = []
    batch_size = 90  # Pinecone inference max batch size is 96 for e5
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        batch_embs = _pinecone_embed(batch, input_type="passage")
        embeddings.extend(batch_embs)
    return embeddings


def embed_query(text: str) -> list[float]:
    """Embed a single query text."""
    return _pinecone_embed([text], input_type="query")[0]


# ── Knowledge Base Manager ──────────────────────────────────────

class KnowledgeBase:
    """Manages the me.txt knowledge base with Pinecone vector store."""

    def __init__(self):
        self.settings = get_settings()
        self.chunks: list[Chunk] = []
        self._pc: Pinecone | None = None
        self._index = None
        self._identity_chunk: Chunk | None = None
        self._last_load_time: float = 0

    def _get_index(self):
        """Lazily initialize Pinecone client and index."""
        if self._index is not None:
            return self._index

        self._pc = Pinecone(api_key=self.settings.pinecone_api_key)

        # Create index if it doesn't exist
        existing = [idx.name for idx in self._pc.list_indexes()]
        if self.settings.pinecone_index_name not in existing:
            logger.info(f"Creating Pinecone index: {self.settings.pinecone_index_name}")
            self._pc.create_index(
                name=self.settings.pinecone_index_name,
                dimension=self.settings.embedding_dimension,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud=self.settings.pinecone_cloud,
                    region=self.settings.pinecone_region,
                ),
            )
            # Wait for index to be ready
            while not self._pc.describe_index(self.settings.pinecone_index_name).status.get("ready"):
                time.sleep(1)

        self._index = self._pc.Index(self.settings.pinecone_index_name)
        return self._index

    def load(self) -> None:
        """Parse me.txt, embed chunks, and upsert to Pinecone."""
        start = time.time()
        logger.info("Loading knowledge base...")

        # Parse
        self.chunks = parse_me_txt(self.settings.me_txt_path)
        if not self.chunks:
            logger.warning("No chunks parsed from me.txt")
            return

        # Find identity chunk (support multiple naming conventions)
        self._identity_chunk = next(
            (c for c in self.chunks if c.section in ("IDENTITY", "PERSONAL IDENTITY")),
            None,
        )

        # Embed all chunks
        texts = [c.text for c in self.chunks]
        embeddings = embed_texts(texts)
        for chunk, emb in zip(self.chunks, embeddings):
            chunk.embedding = emb

        # Upsert to Pinecone
        index = self._get_index()

        # Delete old vectors in namespace first
        try:
            index.delete(delete_all=True, namespace=self.settings.pinecone_namespace)
        except Exception as e:
            logger.warning(f"Could not clear namespace (may be empty): {e}")

        # Upsert in batches of 100
        vectors = []
        for chunk in self.chunks:
            vectors.append({
                "id": chunk.id,
                "values": chunk.embedding,
                "metadata": {
                    "section": chunk.section,
                    "chunk_index": chunk.chunk_index,
                    "token_count": chunk.token_count,
                    "text": chunk.text,
                },
            })

        batch_size = 100
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i : i + batch_size]
            index.upsert(vectors=batch, namespace=self.settings.pinecone_namespace)

        self._last_load_time = time.time()
        elapsed = self._last_load_time - start
        logger.info(
            f"Knowledge base loaded: {len(self.chunks)} chunks, "
            f"upserted to Pinecone in {elapsed:.2f}s"
        )

    def reload(self) -> None:
        """Hot-reload: re-parse, re-embed, re-upsert."""
        logger.info("Hot-reloading knowledge base...")
        self.load()

    def search(self, query: str, top_k: int | None = None) -> list[dict]:
        """
        Embed query and search Pinecone for relevant chunks.
        Always includes the IDENTITY chunk in results.
        """
        if not self.chunks:
            return []

        top_k = top_k or self.settings.rag_top_k
        query_emb = embed_query(query)
        index = self._get_index()

        results = index.query(
            vector=query_emb,
            top_k=top_k + 1,  # +1 in case identity is already in results
            include_metadata=True,
            namespace=self.settings.pinecone_namespace,
        )

        # Build result list
        seen_ids = set()
        output = []

        # Always include IDENTITY first
        if self._identity_chunk:
            output.append({
                "section": self._identity_chunk.section,
                "text": self._identity_chunk.text,
                "score": 1.0,
            })
            seen_ids.add(self._identity_chunk.id)

        # Add top-K results above threshold
        for match in results.matches:
            if match.id in seen_ids:
                continue
            if match.score < self.settings.rag_threshold:
                continue
            output.append({
                "section": match.metadata.get("section", ""),
                "text": match.metadata.get("text", ""),
                "score": match.score,
            })
            seen_ids.add(match.id)

            if len(output) >= top_k + 1:  # +1 for identity
                break

        return output

    @property
    def stats(self) -> dict:
        """Return stats about the loaded knowledge base."""
        return {
            "total_chunks": len(self.chunks),
            "sections": list(set(c.section for c in self.chunks)),
            "total_tokens": sum(c.token_count for c in self.chunks),
            "last_load_time": self._last_load_time,
        }


# ── Singleton ───────────────────────────────────────────────────

_kb_instance: KnowledgeBase | None = None


def get_knowledge_base() -> KnowledgeBase:
    """Get or create the singleton KnowledgeBase instance."""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBase()
    return _kb_instance
