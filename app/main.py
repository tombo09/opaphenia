from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi import _rate_limit_exceeded_handler
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import CORS_ORIGINS
from app.db import init_db, connect
from app.routers import auth, account, thoughts, public
from app.limiter import limiter


def create_app() -> FastAPI:
    app = FastAPI()

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

    init_db()

    # API
    app.include_router(auth.router, prefix="/api")
    app.include_router(account.router, prefix="/api")
    app.include_router(thoughts.router, prefix="/api")
    app.include_router(public.router, prefix="/api")

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
                    """,
                    (username.lower(), thought_id),
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
                    (username.lower(),),
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
