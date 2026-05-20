from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .database import init_db
from .exceptions import AppError
from .routers.contracts import router as contracts_router


app = FastAPI(
    title="AI合同初审助手 V1 Backend",
    version="1.0.0",
    description="微信小程序 V1 后端服务，提供合同上传、解析、审核和历史记录能力。",
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
        },
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务内部异常，请稍后重试",
                "detail": str(exc),
            },
        },
    )


@app.get("/health")
async def health_check() -> dict:
    return {"success": True, "data": {"status": "ok"}}


app.include_router(contracts_router)
