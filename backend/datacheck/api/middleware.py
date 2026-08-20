from uuid import uuid4

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from datacheck.api.errors import unexpected_error_response


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
