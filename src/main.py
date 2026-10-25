import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from api import router
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger


from cache import snapshot_cache
from config import CONFIG
import log

logger = log.setup_custom_logger(__name__)

def refresh_cache():
    return snapshot_cache.refresh()

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    # Initialization is mandatory; never serve a silently recreated in-memory counter.
    await asyncio.get_running_loop().run_in_executor(None, snapshot_cache.stats_store.initialize)
    # Database reads and encoding run off the event loop.
    await asyncio.get_event_loop().run_in_executor(None, refresh_cache)
    scheduler = BackgroundScheduler()
    scheduler.add_job(refresh_cache, trigger=IntervalTrigger(seconds=CONFIG["cache"]["mod_cache_time"]), id="refresh_cache", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)
app.include_router(router, tags=["api"])
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["GET"], allow_headers=["*"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=CONFIG["allowed_hosts"])

@app.get("/", include_in_schema=False)
def read_root() -> RedirectResponse:
    return RedirectResponse(url="/status")

@app.get("/status")
def get_status():
    return {
        "status": "ok",
        "docs_url": f"{CONFIG['fossic']['api_url']}/docs",
        "cache": snapshot_cache.get_status(),
    }
