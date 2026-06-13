"""
Centralized configuration — loads from environment variables.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── LLM (Groq) ──────────────────────────────────────────────
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_max_tokens: int = 1024
    groq_temperature: float = 0.7

    # ── Embeddings (Pinecone Inference) ───────────────────────
    embedding_model: str = "multilingual-e5-large"
    embedding_dimension: int = 1024

    # ── Pinecone ────────────────────────────────────────────────
    pinecone_api_key: str = ""
    pinecone_index_name: str = "portfolio-rag-pinecone"
    pinecone_namespace: str = "me-txt"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"

    # ── RAG Settings ────────────────────────────────────────────
    rag_top_k: int = 4
    rag_threshold: float = 0.35
    me_txt_path: str = "knowledge/me.txt"

    # ── Router ──────────────────────────────────────────────────
    router_confidence_threshold: float = 0.8

    # ── Rate Limiting ───────────────────────────────────────────
    rate_limit: str = "20/minute"

    # ── Tool APIs ───────────────────────────────────────────────
    # Spotify
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_refresh_token: str = ""

    # YouTube
    youtube_api_key: str = ""
    youtube_channel_id: str = ""

    # GitHub
    github_token: str = ""
    github_username: str = ""

    # Last.fm
    lastfm_api_key: str = ""
    lastfm_username: str = ""

    # ── CORS ────────────────────────────────────────────────────
    cors_origins: list[str] = [
        "http://localhost:8080",
        "http://localhost:8081",
        "http://localhost:5173",
        "http://localhost:3000",
        "https://arnv.in",
        "https://arnvfolio.vercel.app",
    ]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
