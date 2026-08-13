"""A bounded newline-delimited JSON protocol for the private Unix socket."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import RequestError

PROTOCOL_VERSION = 1
DEFAULT_MAX_FRAME_BYTES = 64 * 1024
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_METHOD = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")


@dataclass(frozen=True, slots=True)
class RpcRequest:
    """One validated local RPC request."""

    request_id: str
    method: str
    params: dict[str, Any]


def parse_request(value: object) -> RpcRequest:
    """Validate a decoded request without accepting protocol extensions."""
    if not isinstance(value, Mapping):
        raise RequestError("request must be a JSON object")
    if value.get("version") != PROTOCOL_VERSION:
        raise RequestError("unsupported RPC protocol version")
    request_id = value.get("id")
    if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
        raise RequestError("request id is invalid")
    method = value.get("method")
    if not isinstance(method, str) or _METHOD.fullmatch(method) is None:
        raise RequestError("request method is invalid")
    params = value.get("params", {})
    if not isinstance(params, Mapping) or any(not isinstance(key, str) for key in params):
        raise RequestError("request params must be a JSON object")
    return RpcRequest(request_id=request_id, method=method, params=dict(params))


async def read_request(reader: asyncio.StreamReader, *, max_bytes: int) -> RpcRequest | None:
    """Read at most one framed request, returning ``None`` at a clean EOF."""
    try:
        line = await reader.readline()
    except (ValueError, asyncio.LimitOverrunError) as error:
        raise RequestError("RPC frame exceeds the configured limit") from error
    if not line:
        return None
    if len(line) > max_bytes or not line.endswith(b"\n"):
        raise RequestError("RPC frame exceeds the configured limit")
    try:
        value = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RequestError("RPC request is not valid JSON") from error
    return parse_request(value)


def response_ok(request_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """Build a success envelope."""
    return {"version": PROTOCOL_VERSION, "id": request_id, "ok": True, "result": dict(result)}


def response_error(request_id: str, code: str, message: str, **extra: object) -> dict[str, Any]:
    """Build a safe failure envelope."""
    error: dict[str, Any] = {"code": code, "message": message}
    error.update(extra)
    return {"version": PROTOCOL_VERSION, "id": request_id, "ok": False, "error": error}


async def write_response(
    writer: asyncio.StreamWriter, response: Mapping[str, Any], *, max_bytes: int
) -> None:
    """Write one bounded response frame."""
    try:
        encoded = json.dumps(response, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RequestError("RPC response cannot be encoded") from error
    if len(encoded) + 1 > max_bytes:
        encoded = json.dumps(
            response_error("response", "operation_failed", "response exceeds configured limit"),
            separators=(",", ":"),
        ).encode("utf-8")
    writer.write(encoded + b"\n")
    await writer.drain()
