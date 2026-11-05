import logging
import re
from typing import Any

class RedactTokenFilter(logging.Filter):
    """
    Logging filter that intercepts and redacts sensitive credentials:
    - JWT and query parameters: ?token=..., &token=..., ?access_token=..., etc.
    - Bearer authorization headers: Bearer <jwt>
    - Cookie tokens: access_token=..., token=...
    Protects logs from token leakage in URL query strings, request logs, and exception tracebacks.
    """
    QUERY_TOKEN_RE = re.compile(r'([?&](?:token|access_token)=)([^&\s\'"]+)', re.IGNORECASE)
    BEARER_TOKEN_RE = re.compile(r'(Bearer\s+)[A-Za-z0-9\-._~+/]+=*', re.IGNORECASE)
    COOKIE_TOKEN_RE = re.compile(r'((?:token|access_token|authorization)=)[^;\s]+', re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = self._redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: self._redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
                elif isinstance(record.args, tuple):
                    record.args = tuple(self._redact(a) if isinstance(a, str) else a for a in record.args)
                elif isinstance(record.args, list):
                    record.args = [self._redact(a) if isinstance(a, str) else a for a in record.args]
        except Exception:
            pass
        return True

    def _redact(self, text: str) -> str:
        text = self.QUERY_TOKEN_RE.sub(r'\1[REDACTED]', text)
        text = self.BEARER_TOKEN_RE.sub(r'\1[REDACTED]', text)
        text = self.COOKIE_TOKEN_RE.sub(r'\1[REDACTED]', text)
        return text

def setup_token_redaction_logging():
    """
    Attach RedactTokenFilter to root logger, uvicorn loggers, and app loggers
    so all handlers and log records have credentials redacted.
    """
    redact_filter = RedactTokenFilter()
    
    root_logger = logging.getLogger()
    root_logger.addFilter(redact_filter)
    for handler in root_logger.handlers:
        handler.addFilter(redact_filter)
        
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "app.request_logger"):
        log = logging.getLogger(logger_name)
        log.addFilter(redact_filter)
        for handler in log.handlers:
            handler.addFilter(redact_filter)
