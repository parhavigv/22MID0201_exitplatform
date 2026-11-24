import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import (
    agent,
    analytics,
    cases,
    clearance,
    documents,
    health,
    inbox,
    me,
    notifications,
    policy,
    progress,
    tasks,
    workflow,
)

log = logging.getLogger("app.main")
settings = get_settings()


# ---------------------------------------------------------------------------
# APScheduler — nightly sweep (Phase 7)
# ---------------------------------------------------------------------------

def _start_scheduler():
    """Configure and start the APScheduler background scheduler.

    Returns the running scheduler so the lifespan can shut it down cleanly.
    APScheduler runs the sweep in a thread pool — it does not block the
    FastAPI event loop.
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from app.jobs.sweep import sweep_all_active

    scheduler = BackgroundScheduler(
        job_defaults={"misfire_grace_time": 600, "coalesce": True},
    )
    scheduler.add_job(
        sweep_all_active,
        trigger=CronTrigger(hour=settings.sweep_hour, minute=settings.sweep_minute),
        id="nightly_sweep",
        name="Nightly exit case sweep",
        replace_existing=True,
    )
    scheduler.start()
    log.info(
        "APScheduler started — nightly sweep at %02d:%02d",
        settings.sweep_hour, settings.sweep_minute,
    )
    return scheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    scheduler = None
    if settings.configured and settings.sweep_enabled:
        try:
            scheduler = _start_scheduler()
        except Exception as exc:
            log.warning("Could not start APScheduler: %s — sweep disabled for this run.", exc)

    yield  # ← FastAPI serves requests while the context is held open

    if scheduler is not None:
        scheduler.shutdown(wait=False)
        log.info("APScheduler shut down.")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Exit Process API",
    version="0.1.0",
    description=(
        "Backend for the employee offboarding platform. Every handler acts "
        "through an RLS-bound Supabase client built from the caller's JWT."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(me.router, prefix="/api")
app.include_router(cases.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(workflow.router, prefix="/api")
app.include_router(inbox.router, prefix="/api")
app.include_router(clearance.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(progress.router, prefix="/api")
app.include_router(policy.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
