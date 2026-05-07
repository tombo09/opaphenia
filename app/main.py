from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi import _rate_limit_exceeded_handler
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import CORS_ORIGINS
from app.db import init_db
from app.routers import auth, account, thoughts, public
from app.limiter import limiter

def create_app() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    init_db()

    app.include_router(auth.router, prefix="/api")
    app.include_router(account.router, prefix="/api")
    app.include_router(thoughts.router, prefix="/api")
    app.include_router(public.router, prefix="/api")

    app.mount("/js", StaticFiles(directory="frontend/js"), name="js")

    app.mount("/css", StaticFiles(directory="frontend/css"), name="css")

    @app.get("/{username}/{thought_id}")
    def public_string_page(username: str, thought_id: int):
        return FileResponse("frontend/index.html")

    @app.get("/{username}")
    def public_profile_page(username: str):
        blocked = {
            "api",
            "app.js",
            "styles.css",
            "favicon.ico",
            "subpage.html",
            "subpage.js",
            "index.html",
        }
        if username in blocked:
            return FileResponse(f"frontend/{username}")
        return FileResponse("frontend/index.html")

    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

    return app


app = create_app()
