from uuid import uuid4

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from datacheck.api.errors import error_response, unexpected_error_response
from datacheck.datasets.csv import MAX_UPLOAD_REQUEST_BYTES


class _RequestBodyTooLarge(Exception):
    pass


class DatasetUploadSizeLimitMiddleware:
    """Bound upload bytes before Starlette can spool an oversized file part."""

    def __init__(self, application: ASGIApp) -> None:
        self._application = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_upload(scope):
            await self._application(scope, receive, send)
            return

        if self._declared_too_large(scope):
            await self._send_too_large(scope, receive, send)
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_UPLOAD_REQUEST_BYTES:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._application(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await self._send_too_large(scope, receive, send)

    @staticmethod
    def _is_upload(scope: Scope) -> bool:
        path = str(scope.get("path", ""))
        return (
            scope.get("type") == "http"
            and scope.get("method") == "POST"
            and path.startswith("/api/v1/datasets/")
            and path.endswith("/upload")
        )

    @staticmethod
    def _declared_too_large(scope: Scope) -> bool:
        values = [
            value for name, value in scope.get("headers", []) if name.lower() == b"content-length"
        ]
        if len(values) != 1:
            return False
        try:
            length = int(values[0].decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            return False
        return length > MAX_UPLOAD_REQUEST_BYTES

    @staticmethod
    async def _send_too_large(scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive=receive)
        response = error_response(
            request,
            status_code=413,
            code="upload_too_large",
            message="Upload exceeds the accepted size limit.",
        )
        await response(scope, receive, send)


class TraceIdMiddleware:
    """Assign a server-controlled trace ID and expose it on every HTTP response."""

    def __init__(self, application: ASGIApp) -> None:
        self._application = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._application(scope, receive, send)
            return

        trace_id = uuid4().hex
        scope.setdefault("state", {})["trace_id"] = trace_id

        async def send_with_trace(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-trace-id", trace_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        await self._application(scope, receive, send_with_trace)


class SanitizedExceptionMiddleware:
    """Converge otherwise-unhandled HTTP failures without disclosing internals."""

    def __init__(self, application: ASGIApp) -> None:
        self._application = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._application(scope, receive, send)
            return

        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._application(scope, receive, tracked_send)
        except Exception:
            if response_started:
                raise
            request = Request(scope, receive=receive)
            await unexpected_error_response(request)(scope, receive, send)
