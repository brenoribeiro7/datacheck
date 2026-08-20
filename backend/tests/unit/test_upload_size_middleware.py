import asyncio

from starlette.types import Message, Receive, Scope, Send

from datacheck.api.middleware import DatasetUploadSizeLimitMiddleware
from datacheck.datasets.csv import MAX_UPLOAD_REQUEST_BYTES


def _scope(*, content_length: int | None = None) -> Scope:
    headers = [] if content_length is None else [(b"content-length", str(content_length).encode())]
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/datasets/00000000-0000-0000-0000-000000000001/upload",
        "raw_path": b"/api/v1/datasets/id/upload",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }


def _run(
    *,
    chunks: list[bytes],
    content_length: int | None = None,
) -> list[Message]:
    messages = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    sent: list[Message] = []

    async def receive() -> Message:
        return messages.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    async def downstream(_scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = DatasetUploadSizeLimitMiddleware(downstream)
    asyncio.run(middleware(_scope(content_length=content_length), receive, send))
    return sent


def test_upload_guard_rejects_declared_or_streamed_excess() -> None:
    early = _run(chunks=[b"unused"], content_length=MAX_UPLOAD_REQUEST_BYTES + 1)
    assert early[0]["status"] == 413

    streamed = _run(chunks=[b"x" * MAX_UPLOAD_REQUEST_BYTES, b"x"])
    assert streamed[0]["status"] == 413


def test_upload_guard_accepts_exact_request_boundary() -> None:
    sent = _run(chunks=[b"x" * MAX_UPLOAD_REQUEST_BYTES])
    assert sent[0]["status"] == 204
