from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi import _rate_limit_exceeded_handler
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import CORS_ORIGINS
from app.db import init_db, connect
from app.migrations import run_migrations
from app.routers import auth, account, thoughts, public, eth
from app.limiter import limiter
from app.thought_delivery import start_recovery_worker
from app.email_outbox import start_email_outbox_worker
from app.rate_limit import start_rate_limit_cleanup_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    run_migrations()
    stop_event, thread = start_recovery_worker()
    email_stop, email_thread = start_email_outbox_worker()
    cleanup_stop, cleanup_thread = start_rate_limit_cleanup_worker()
    try:
        yield
    finally:
        stop_event.set()
        email_stop.set()
        cleanup_stop.set()
        thread.join(timeout=5)
        email_thread.join(timeout=5)
        cleanup_thread.join(timeout=5)


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    app.state.limiter = limiter
    app.add_exception_handler(
        RateLimitExceeded,
        _rate_limit_exceeded_handler
    )

    app.add_middleware(SlowAPIMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API
    app.include_router(auth.router, prefix="/api")
    app.include_router(account.router, prefix="/api")
    app.include_router(thoughts.router, prefix="/api")
    app.include_router(public.router, prefix="/api")
    app.include_router(eth.router, prefix="/api")

    # Static directories
    app.mount(
        "/js",
        StaticFiles(directory="frontend/js"),
        name="js"
    )

    app.mount(
        "/css",
        StaticFiles(directory="frontend/css"),
        name="css"
    )

    # Root page
    @app.get("/")
    def index():
        return FileResponse("frontend/index.html")

    # Falls diese Dateien tatsächlich existieren
    @app.get("/favicon.ico")
    def favicon():
        return FileResponse("frontend/favicon.ico")

    @app.get("/subpage.html")
    def subpage():
        return FileResponse("frontend/subpage.html")

    @app.get("/subpage.js")
    def subpage_js():
        return FileResponse("frontend/subpage.js")

    # Owner detail shell. Authorization and data access remain in
    # GET /api/thoughts/{thought_id}.
    @app.get("/own/thoughts/{thought_id:int}")
    def own_thought_page(thought_id: int):
        return FileResponse("frontend/index.html")

    # Public thought page
    @app.get("/{username}/{thought_id:int}")
    def public_string_page(username: str, thought_id: int):
        con = connect()

        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM thoughts t
                    JOIN users u ON u.id = t.user_id
                    WHERE lower(u.username) = %s
                      AND t.id = %s
                      AND u.strings_public = TRUE
                      AND t.published_at IS NOT NULL
                    """,
                    (username.strip().lower(), thought_id),
                )

                if not cur.fetchone():
                    raise HTTPException(status_code=404)

        finally:
            con.close()

        return FileResponse("frontend/index.html")

    # Public profile page
    @app.get("/{username}")
    def public_profile_page(username: str):
        con = connect()

        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM users
                    WHERE lower(username) = %s
                      AND strings_public = TRUE
                    """,
                    (username.strip().lower(),),
                )

                if not cur.fetchone():
                    raise HTTPException(status_code=404)

        finally:
            con.close()

        return FileResponse("frontend/index.html")

    # Alles andere
    app.mount(
        "/",
        StaticFiles(directory="frontend", html=True),
        name="frontend"
    )

    return app


app = create_app()
