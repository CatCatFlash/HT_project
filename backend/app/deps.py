from fastapi import Header

from .config import ALLOW_DEMO_USER_FALLBACK, DEMO_USER_FALLBACK_VALUE
from .exceptions import AppError


def get_user_id(x_user_id: str | None = Header(default=None)) -> str:
    if x_user_id and x_user_id.strip():
        return x_user_id.strip()
    if ALLOW_DEMO_USER_FALLBACK:
        return DEMO_USER_FALLBACK_VALUE
    raise AppError(
        "MISSING_USER_ID",
        "缺少 X-User-Id，请先完成用户身份标识后再访问该接口",
        401,
    )
