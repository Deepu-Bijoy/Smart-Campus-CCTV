from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

class CustomHTTPException(Exception):
    def __init__(self, status_code: int, detail: str, code: str = "ERROR"):
        self.status_code = status_code
        self.detail = detail
        self.code = code

async def custom_http_exception_handler(request: Request, exc: CustomHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
    )

def setup_exception_handlers(app: FastAPI):
    app.add_exception_handler(CustomHTTPException, custom_http_exception_handler)
