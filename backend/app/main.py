from pathlib import Path

import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .exceptions import AppError
from .routers.contracts import router as contracts_router
from .routers.progress_admin import router as progress_admin_router
from .trace import get_trace_id, new_trace_id, set_trace_id


logger = logging.getLogger(__name__)


app = FastAPI(
    title="AI合同初审助手 V1 Backend",
    version="1.0.0",
    description="微信小程序 V1 后端服务，提供合同上传、解析、审核和历史记录能力。",
)

app.mount(
    "/admin-assets",
    StaticFiles(directory=Path(__file__).resolve().parent / "static"),
    name="admin-assets",
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.middleware("http")
async def inject_trace_id(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id", "").strip() or new_trace_id()
    set_trace_id(trace_id)
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    trace_id = get_trace_id()
    logger.warning(
        "request failed code=%s phase=%s trace_id=%s path=%s",
        exc.code,
        exc.phase or "",
        trace_id,
        request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
            "trace_id": trace_id,
        },
        headers={"X-Trace-Id": trace_id},
    )


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    trace_id = get_trace_id()
    logger.warning(
        "request validation failed trace_id=%s path=%s errors=%s",
        trace_id,
        request.url.path,
        exc.errors(),
    )
    return JSONResponse(
        status_code=400,
        content={
            "success": False,
            "error": {
                "code": "UPLOAD_INVALID_REQUEST",
                "message": "上传请求格式异常，请重新选择文件后再试",
            },
            "trace_id": trace_id,
        },
        headers={"X-Trace-Id": trace_id},
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    trace_id = get_trace_id()
    logger.exception(
        "unexpected request error trace_id=%s path=%s",
        trace_id,
        request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务暂时开小差了，请稍后重试",
            },
            "trace_id": trace_id,
        },
        headers={"X-Trace-Id": trace_id},
    )


@app.get("/health")
async def health_check() -> dict:
    return {"success": True, "data": {"status": "ok"}}


app.include_router(contracts_router)
app.include_router(progress_admin_router)
