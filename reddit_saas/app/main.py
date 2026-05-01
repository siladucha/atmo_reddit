from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.routes import auth, dashboard, review, pipeline

settings = get_settings()

app = FastAPI(
    title="Reddit Marketing SaaS",
    version="0.1.0",
    docs_url="/docs" if settings.app_env == "development" else None,
)

# Static files & templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Routes
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(dashboard.router, prefix="/admin", tags=["admin"])
app.include_router(review.router, prefix="/review", tags=["review"])
app.include_router(pipeline.router, prefix="/pipeline", tags=["pipeline"])


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "0.1.0"}
