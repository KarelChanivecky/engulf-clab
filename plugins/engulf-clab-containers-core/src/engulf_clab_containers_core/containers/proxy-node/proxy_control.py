#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from pathlib import Path
from urllib.parse import parse_qs
import json
import os

STATE_PATH = Path("/etc/squid/proxy-control.json")
SQUID_CONF = Path("/etc/squid/squid.conf")
LISTEN = ("0.0.0.0", 8890)

DEFAULT_STATE = {
    "suppress_proxy_headers": True,
    "disable_cache": True,
    "parent_enabled": False,
    "parent_host": "10.1.100.6",
    "parent_port": 8080,
    "forward_proxy_auth": True,
}


def load_state():
    try:
        state = json.loads(STATE_PATH.read_text())
    except Exception:
        state = {}
    merged = DEFAULT_STATE.copy()
    merged.update({k: state[k] for k in DEFAULT_STATE if k in state})
    try:
        merged["parent_port"] = int(merged["parent_port"])
    except (TypeError, ValueError):
        merged["parent_port"] = DEFAULT_STATE["parent_port"]
    return merged


def checkbox(value):
    return "checked" if value else ""


def render_config(state):
    lines = [
        "http_port 0.0.0.0:8888",
        "pid_filename /run/squid.pid",
        "coredump_dir /var/spool/squid",
        "",
        "acl all_clients src all",
        "http_access allow manager localhost",
        "http_access deny manager",
        "always_direct allow manager",
        "cachemgr_passwd none config",
        "http_access allow all_clients",
        "",
    ]

    if state["suppress_proxy_headers"]:
        lines.extend(
            [
                "via off",
                "forwarded_for delete",
                "request_header_access X-Forwarded-For deny all",
                "request_header_access Via deny all",
                "request_header_access Forwarded deny all",
                "request_header_access X-Real-IP deny all",
                "request_header_access All allow all",
                "",
                "reply_header_access Via deny all",
                "reply_header_access X-Cache deny all",
                "reply_header_access X-Cache-Lookup deny all",
                "reply_header_access All allow all",
                "",
            ]
        )
    else:
        lines.extend(["via on", "forwarded_for on", ""])

    if state["disable_cache"]:
        lines.extend(["cache deny all", ""])

    if state["parent_enabled"]:
        auth = " login=PASS" if state["forward_proxy_auth"] else ""
        host = str(state["parent_host"]).strip()
        port = int(state["parent_port"])
        lines.extend(
            [
                f"cache_peer {host} parent {port} 0 no-query default name=parent_proxy{auth}",
                "never_direct deny manager",
                "never_direct allow all",
                "",
            ]
        )

    lines.extend(
        [
            "access_log /var/log/squid/access.log",
            "cache_log /var/log/squid/cache.log",
            "",
        ]
    )
    return "\n".join(lines)


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    SQUID_CONF.write_text(render_config(state))
    os.utime(SQUID_CONF, None)


def html(state, message=""):
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Proxy Control</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 760px; margin: 32px auto; padding: 0 16px; }}
    label {{ display: block; margin: 14px 0; }}
    input[type=text], input[type=number] {{ width: 240px; padding: 6px; }}
    button {{ padding: 8px 14px; }}
    pre {{ background: #f5f5f5; padding: 12px; overflow: auto; }}
    .ok {{ color: #176317; }}
  </style>
</head>
<body>
  <h1>Proxy Control</h1>
  <p class="ok">{escape(message)}</p>
  <form method="post">
    <label><input type="checkbox" name="suppress_proxy_headers" {checkbox(state["suppress_proxy_headers"])}> Suppress Via, X-Forwarded-For, Forwarded, X-Real-IP, and cache headers</label>
    <label><input type="checkbox" name="disable_cache" {checkbox(state["disable_cache"])}> Disable Squid cache</label>
    <label><input type="checkbox" name="parent_enabled" {checkbox(state["parent_enabled"])}> Use a parent proxy</label>
    <label>Parent host <input type="text" name="parent_host" value="{escape(str(state["parent_host"]))}"></label>
    <label>Parent port <input type="number" name="parent_port" min="1" max="65535" value="{int(state["parent_port"])}"></label>
    <label><input type="checkbox" name="forward_proxy_auth" {checkbox(state["forward_proxy_auth"])}> Forward browser proxy authentication to parent proxy</label>
    <button type="submit">Apply</button>
  </form>
  <h2>Generated squid.conf</h2>
  <pre>{escape(render_config(state))}</pre>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.respond(load_state())

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        fields = parse_qs(self.rfile.read(length).decode("utf-8"))
        state = {
            "suppress_proxy_headers": "suppress_proxy_headers" in fields,
            "disable_cache": "disable_cache" in fields,
            "parent_enabled": "parent_enabled" in fields,
            "parent_host": fields.get("parent_host", [DEFAULT_STATE["parent_host"]])[0],
            "parent_port": int(fields.get("parent_port", [DEFAULT_STATE["parent_port"]])[0]),
            "forward_proxy_auth": "forward_proxy_auth" in fields,
        }
        state["parent_port"] = max(1, min(65535, state["parent_port"]))
        save_state(state)
        self.respond(state, "Configuration written; Squid will reload within a few seconds.")

    def respond(self, state, message=""):
        body = html(state, message).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)


if __name__ == "__main__":
    save_state(load_state())
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
