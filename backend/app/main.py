"""Aplicação FastAPI. Execução: `uvicorn app.main:app --port 8000`.

Todas as rotas ficam sob /api/v1. OpenAPI em /api/v1/openapi.json.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import OperationalError

from app import __version__
from app.api import accuracy, alerts, auth, favorites, opportunities, predictions, signals, system, tokens
from app.config import get_settings
from app.logging_setup import setup_logging

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    setup_logging()
    s = get_settings()
    app = FastAPI(
        title="MemeCoinAI API", version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json", docs_url=f"{API_PREFIX}/docs", redoc_url=None,
    )
    if s.cors_origin_list:
        app.add_middleware(
            CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type"],
        )

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            body = exc.detail
        else:
            body = {"code": "http_error", "message": str(exc.detail)}
        return JSONResponse({"error": body}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(OperationalError)
    async def database_busy(_: Request, exc: OperationalError):
        # SQLite ocupado por uma escrita longa: erro temporário, não falha da aplicação.
        if "locked" in str(exc.orig).lower() or "busy" in str(exc.orig).lower():
            return JSONResponse({"error": {"code": "database_busy", "message": "Banco ocupado pelo coletor; tente de novo em instantes."}},
                                status_code=503, headers={"Retry-After": "2"})
        raise exc

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse({"error": {"code": "validation_error", "message": "Parâmetros inválidos", "details": details}}, status_code=422)

    for r in (auth.router, system.router, tokens.router, alerts.router, predictions.router, signals.router, opportunities.router, accuracy.router, favorites.router):
        app.include_router(r, prefix=API_PREFIX)
    _mount_frontend(app, Path(s.frontend_dist_dir))
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve o build do frontend (SPA) se existir. Registrado depois da API."""
    index = dist / "index.html"
    if not index.is_file():
        return
    root = dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Rota de API inexistente"})
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        # Rotas do cliente (/tokens/..., /alerts/...) recebem o index.html.
        return FileResponse(index)


app = create_app()
