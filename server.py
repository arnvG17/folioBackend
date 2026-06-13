"""
FastAPI Server — Main entry point with middleware, CORS, and lifecycle hooks.
"""

import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import get_settings
from knowledge_base import get_knowledge_base
from rag_endpoint import rag_router

# ── Logging ─────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-20s │ %(levelname)-8s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Rate Limiter ────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)


# ── Lifecycle ───────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle hooks."""
    settings = get_settings()
    logger.info("🚀 Starting Portfolio Smart Agent...")

    # Load knowledge base on startup
    kb = get_knowledge_base()
    try:
        kb.load()
        logger.info(f"✅ Knowledge base loaded: {kb.stats}")
    except Exception as e:
        logger.error(f"❌ Knowledge base failed to load: {e}")
        logger.info("   Server will start without knowledge base — /rag personal queries may fail.")

    # Start file watcher for hot-reload (background task)
    watcher_task = asyncio.create_task(_watch_me_txt(settings.me_txt_path))

    logger.info("✅ Smart Agent ready!")
    yield

    # Shutdown
    watcher_task.cancel()
    logger.info("👋 Shutting down...")


async def _watch_me_txt(path: str):
    """Watch me.txt for changes and hot-reload the knowledge base."""
    try:
        from watchfiles import awatch
        logger.info(f"👁️ Watching {path} for changes...")

        async for changes in awatch(path):
            logger.info(f"📝 me.txt changed: {changes}")
            kb = get_knowledge_base()
            try:
                kb.reload()
                logger.info(f"✅ Knowledge base hot-reloaded: {kb.stats}")
            except Exception as e:
                logger.error(f"❌ Hot-reload failed: {e}")

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning(f"File watcher error (non-fatal): {e}")


# ── App ─────────────────────────────────────────────────────────

app = FastAPI(
    title="Portfolio Smart Agent",
    description="RAG-powered portfolio chatbot with intelligent routing and tool integrations",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes
app.include_router(rag_router)


# ── Health & Info ───────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check endpoint."""
    kb = get_knowledge_base()
    return {
        "status": "ok",
        "service": "portfolio-smart-agent",
        "knowledge_base": kb.stats,
    }


@app.get("/me.txt")
async def get_me_txt():
    """Serve the raw me.txt file (for the RagManager frontend)."""
    import os
    path = get_settings().me_txt_path
    if os.path.exists(path):
        return FileResponse(path, media_type="text/plain")
    return JSONResponse({"error": "me.txt not found"}, status_code=404)


@app.post("/reload")
async def reload_knowledge_base():
    """Manually trigger knowledge base reload."""
    kb = get_knowledge_base()
    try:
        kb.reload()
        return {"status": "ok", "stats": kb.stats}
    except Exception as e:
        return JSONResponse(
            {"error": f"Reload failed: {str(e)}"},
            status_code=500,
        )


@app.post("/me.txt")
async def save_me_txt(request: Request):
    """Save new me.txt content and trigger reload."""
    import os
    body = await request.json()
    content = body.get("content", "")

    if not content.strip():
        return JSONResponse({"error": "Content cannot be empty"}, status_code=400)

    path = get_settings().me_txt_path
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    # Trigger reload
    kb = get_knowledge_base()
    try:
        kb.reload()
        return {
            "status": "ok",
            "message": "me.txt saved and knowledge base reloaded",
            "stats": kb.stats,
        }
    except Exception as e:
        return JSONResponse(
            {"error": f"Saved but reload failed: {str(e)}"},
            status_code=500,
        )


@app.get("/config/status")
async def config_status():
    """Return which integrations are configured (without exposing keys)."""
    s = get_settings()

    def _is_set(val: str) -> bool:
        return bool(val and val.strip() and not val.startswith("pcsk_xxx") and not val.startswith("gsk_xxx"))

    return {
        "groq": _is_set(s.groq_api_key),
        "google_embeddings": _is_set(s.google_api_key),
        "pinecone": _is_set(s.pinecone_api_key),
        "spotify": _is_set(s.spotify_client_id) and _is_set(s.spotify_refresh_token),
        "youtube": _is_set(s.youtube_api_key) and _is_set(s.youtube_channel_id),
        "github": _is_set(s.github_username),
        "pinecone_index": s.pinecone_index_name,
        "groq_model": s.groq_model,
    }


@app.post("/config/test-tool")
async def test_tool(request: Request):
    """Test a specific tool integration."""
    body = await request.json()
    tool_name = body.get("tool", "")

    from tools.spotify import SpotifyTool
    from tools.youtube import YouTubeTool
    from tools.github import GitHubTool

    tools = {
        "spotify": SpotifyTool(),
        "youtube": YouTubeTool(),
        "github": GitHubTool(),
    }

    if tool_name not in tools:
        return JSONResponse({"error": f"Unknown tool: {tool_name}"}, status_code=400)

    try:
        result = await tools[tool_name].run()
        return {"status": "ok", "tool": tool_name, "result": result}
    except Exception as e:
        return JSONResponse(
            {"status": "error", "tool": tool_name, "error": str(e)},
            status_code=500,
        )


# ── Run ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=5000, reload=True)

