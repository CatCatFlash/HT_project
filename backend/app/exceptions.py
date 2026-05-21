class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, phase: str | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.phase = phase
        super().__init__(message)


class UploadError(AppError):
    pass


class ParseError(AppError):
    pass


class AuditError(AppError):
    pass


class NotFoundError(AppError):
    def __init__(self, message: str = "记录不存在"):
        super().__init__("NOT_FOUND", message, 404)
