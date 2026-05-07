import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import init_db
from core.ollama import ollama
from api.models import HealthResponse
from api.routes import pipeline, portfolio, social, crm, inspiration, intelligence, lightroom, shoots, content, print as print_routes, settings as settings_routes
from api.routes.intelligence import images_router
from api.routes import sd_import


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="LENS API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pipeline.router, prefix="/pipeline", tags=["pipeline"])
app.include_router(portfolio.router, prefix="/portfolio", tags=["portfolio"])
app.include_router(social.router, prefix="/social", tags=["social"])
app.include_router(crm.router, prefix="/crm", tags=["crm"])
app.include_router(inspiration.router, prefix="/inspiration", tags=["inspiration"])
app.include_router(intelligence.router, prefix="/intelligence", tags=["intelligence"])
app.include_router(lightroom.router, prefix="/lightroom", tags=["lightroom"])
app.include_router(shoots.router, prefix="/shoots", tags=["shoots"])
app.include_router(content.router, prefix="/api/v1/content", tags=["content"])
app.include_router(print_routes.router, prefix="/api/v1/print", tags=["print"])
app.include_router(images_router, prefix="/api/v1", tags=["images"])
app.include_router(sd_import.router, prefix="/api/v1/import", tags=["sd-import"])
app.include_router(settings_routes.router, prefix="/settings", tags=["settings"])


@app.get("/health", response_model=HealthResponse)
async def health():
    ollama_ok = await ollama.health()
    return HealthResponse(
        status="ok",
        ollama=ollama_ok,
        db=str(settings.lens_db_path),
    )


if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=settings.lens_api_port,
        reload=False,
        log_level="info",
        timeout_keep_alive=600,   # 32b model calls can take several minutes
    )
