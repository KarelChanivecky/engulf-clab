from __future__ import annotations

import http.client
import logging
import os
import socket
import sqlite3
import ssl
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dnslib import RCODE, DNSError, DNSRecord
from dnslib.server import BaseResolver, DNSServer

LOG = logging.getLogger("eclab.dns-cache")
DB_PATH = Path(os.environ.get("ECLAB_DNS_CACHE_DB", "/var/lib/eclab-dns-cache/cache.sqlite3"))


@dataclass(frozen=True, slots=True)
class Upstream:
    scheme: str
    host: str
    port: int
    path: str = "/dns-query"

    @property
    def label(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


def _domains() -> tuple[str, ...]:
    raw = os.environ.get("ECLAB_DNS_CACHE_DOMAINS", "")
    domains = tuple(
        value.strip().rstrip(".").encode("idna").decode("ascii").lower()
        for value in raw.split(",")
        if value.strip()
    )
    if not domains:
        raise ValueError("ECLAB_DNS_CACHE_DOMAINS must contain at least one domain")
    return domains


def _upstreams() -> tuple[Upstream, ...]:
    raw = os.environ.get("ECLAB_DNS_CACHE_UPSTREAM", "udp://1.1.1.1:53")
    values: list[Upstream] = []
    for value in raw.split(","):
        endpoint = value.strip()
        if not endpoint:
            raise ValueError("ECLAB_DNS_CACHE_UPSTREAM must not contain empty endpoints")
        if "://" not in endpoint:
            endpoint = f"udp://{endpoint}"
        parsed = urlsplit(endpoint)
        scheme = {"cleartext": "udp", "dot": "tls", "doh": "https"}.get(
            parsed.scheme.lower(), parsed.scheme.lower()
        )
        if scheme not in {"udp", "tcp", "tls", "https"}:
            raise ValueError(f"unsupported DNS upstream transport in {value!r}")
        if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError(f"invalid DNS upstream endpoint {value!r}")
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError(f"invalid port in DNS upstream {value!r}") from error
        if port is None:
            port = {"udp": 53, "tcp": 53, "tls": 853, "https": 443}[scheme]
        if not 1 <= port <= 65535:
            raise ValueError(f"invalid upstream port in {value!r}")
        if scheme != "https" and (parsed.path not in ("", "/") or parsed.query):
            raise ValueError(f"DNS transport endpoint {value!r} must not include a path or query")
        if scheme == "https" and parsed.query == "":
            path = parsed.path or "/dns-query"
        elif scheme == "https":
            path = f"{parsed.path or '/dns-query'}?{parsed.query}"
        else:
            path = "/dns-query"
        values.append(Upstream(scheme, parsed.hostname, port, path))
    if not values:
        raise ValueError("ECLAB_DNS_CACHE_UPSTREAM must contain at least one endpoint")
    return tuple(values)


def _read_exact(connection: socket.socket, size: int, deadline: float) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("DNS upstream timeout")
        connection.settimeout(remaining)
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            raise OSError("DNS upstream closed the connection early")
        chunks.extend(chunk)
    return bytes(chunks)


def _exchange(upstream: Upstream, request: DNSRecord, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    if upstream.scheme in {"udp", "tcp"}:
        response = request.send(
            upstream.host,
            upstream.port,
            tcp=upstream.scheme == "tcp",
            timeout=timeout,
        )
        parsed = DNSRecord.parse(response)
        if upstream.scheme == "udp" and parsed.header.tc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("DNS upstream timeout during TCP retry")
            response = request.send(upstream.host, upstream.port, tcp=True, timeout=remaining)
        return response
    if upstream.scheme == "tls":
        with (
            socket.create_connection((upstream.host, upstream.port), timeout=timeout) as raw,
            ssl.create_default_context().wrap_socket(raw, server_hostname=upstream.host) as connection,
        ):
            connection.settimeout(timeout)
            payload = request.pack()
            connection.sendall(struct.pack("!H", len(payload)) + payload)
            length = struct.unpack("!H", _read_exact(connection, 2, deadline))[0]
            return _read_exact(connection, length, deadline)
    connection = http.client.HTTPSConnection(
        upstream.host,
        upstream.port,
        timeout=timeout,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            "POST",
            upstream.path,
            body=request.pack(),
            headers={
                "Content-Type": "application/dns-message",
                "Accept": "application/dns-message",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise OSError(f"DoH upstream returned HTTP {response.status}")
        return response.read()
    finally:
        connection.close()


class PersistentResolver(BaseResolver):
    def __init__(self, domains: tuple[str, ...], upstreams: tuple[Upstream, ...], timeout: float):
        self.domains = domains
        self.upstreams = upstreams
        self.timeout = timeout
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.lock = threading.Lock()
        with self.db:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS answers ("
                "qname TEXT NOT NULL, qtype INTEGER NOT NULL, qclass INTEGER NOT NULL, "
                "response BLOB NOT NULL, PRIMARY KEY (qname, qtype, qclass))"
            )

    def _is_cached_domain(self, name: str) -> bool:
        normalized = name.rstrip(".").lower()
        return any(normalized == domain or normalized.endswith("." + domain) for domain in self.domains)

    def _cached(self, key: tuple[str, int, int], request: DNSRecord) -> DNSRecord | None:
        with self.lock:
            row = self.db.execute(
                "SELECT response FROM answers WHERE qname=? AND qtype=? AND qclass=?", key
            ).fetchone()
        if row is None:
            return None
        response = DNSRecord.parse(row[0])
        response.header.id = request.header.id
        # Stored answers do not expire, while zero TTL avoids clients retaining stale copies.
        for section in (response.rr, response.auth, response.ar):
            for record in section:
                record.ttl = 0
        return response

    def _store(self, key: tuple[str, int, int], response: DNSRecord) -> None:
        if response.header.rcode != RCODE.NOERROR or not response.rr:
            return
        stored = DNSRecord.parse(response.pack())
        stored.header.id = 0
        payload = stored.pack()
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO answers(qname,qtype,qclass,response) VALUES(?,?,?,?) "
                "ON CONFLICT(qname,qtype,qclass) DO UPDATE SET response=excluded.response",
                (*key, payload),
            )

    def resolve(self, request: DNSRecord, handler: object) -> DNSRecord:
        del handler
        question = request.questions[0]
        key = (str(question.qname).rstrip(".").lower(), question.qtype, question.qclass)
        cacheable = self._is_cached_domain(key[0])
        last_error: Exception | None = None
        last_response: DNSRecord | None = None
        deadline = time.monotonic() + self.timeout
        for upstream in self.upstreams:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                response = _exchange(upstream, request, remaining)
                parsed = DNSRecord.parse(response)
                parsed.header.id = request.header.id
                if parsed.header.rcode == RCODE.NOERROR and parsed.rr:
                    if cacheable:
                        self._store(key, parsed)
                    return parsed
                last_response = parsed
                if parsed.header.rcode == RCODE.NOERROR:
                    return parsed
                LOG.warning("upstream %s returned %s", upstream.label, RCODE[parsed.header.rcode])
            except (DNSError, http.client.HTTPException, OSError, TimeoutError) as error:
                last_error = error
                LOG.warning("upstream %s failed: %s", upstream.label, error)
        if cacheable:
            cached = self._cached(key, request)
            if cached is not None:
                LOG.info("serving cached answer for %s", key[0])
                return cached
        if last_response is not None:
            return last_response
        LOG.error("no upstream answer for %s%s", key[0], f": {last_error}" if last_error else "")
        reply = request.reply()
        reply.header.rcode = RCODE.SERVFAIL
        return reply


def main() -> None:
    timeout = float(os.environ.get("ECLAB_DNS_CACHE_UPSTREAM_TIMEOUT", "5"))
    if not 0.1 <= timeout <= 120:
        raise ValueError("ECLAB_DNS_CACHE_UPSTREAM_TIMEOUT must be between 0.1 and 120 seconds")
    logging.basicConfig(level=os.environ.get("ECLAB_DNS_CACHE_LOG_LEVEL", "INFO"))
    resolver = PersistentResolver(_domains(), _upstreams(), timeout)
    for tcp in (False, True):
        DNSServer(resolver, port=53, address="0.0.0.0", tcp=tcp).start_thread()
    LOG.info("DNS cache ready for %s", ", ".join(resolver.domains))
    threading.Event().wait()


if __name__ == "__main__":
    main()
