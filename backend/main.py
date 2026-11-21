import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.controllers.api import register_routes
from backend.models.store import Store
from backend.services.analysis import AnalysisError
from backend.services.auth import signing_key
from backend.services.digests import digest_loop
from backend.services.jobs import Jobs
from backend.services.llm_client import MessagesModel, ModelError

logger = logging.getLogger(__name__)


def create_app(store=None, model=None, verifier=None):
    store = store or Store()
    model = model or MessagesModel()

    @asynccontextmanager
    async def lifespan(app):
        with store.scheduler_lock():
            store.setup()
            app.state.signing_key = signing_key()
            app.state.jobs = Jobs(store, model, **({"verifier": verifier} if verifier else {}))
            app.state.jobs.recover()
            digest_task = asyncio.create_task(digest_loop(store))
            try:
                yield
            finally:
                digest_task.cancel()
                await asyncio.gather(digest_task, return_exceptions=True)
                await app.state.jobs.close()

    app = FastAPI(title="经营归因分析系统 API", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(httpx.HTTPError)
    def warehouse_error(_, exc):
        logger.warning("Warehouse request failed: %s", type(exc).__name__)
        return JSONResponse({"detail": "数仓请求失败，请检查连接及初始化状态"}, status_code=503)

    @app.exception_handler(AnalysisError)
    def analysis_error(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(ModelError)
    def model_error(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.middleware("http")
    async def audit_requests(request, call_next):
        response = await call_next(request)
        if username := getattr(request.state, "username", None):
            route = request.scope.get("route")
            await asyncio.to_thread(
                store.audit, username, "api.request", getattr(route, "path", "unknown"),
                {"method": request.method, "status": response.status_code},
            )
        return response

    register_routes(app, store, model)
    return app


app = create_app()

if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8000)
