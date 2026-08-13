from __future__ import annotations

import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from engulf_clab_mcp.bridge import UnixRpcClient
from engulf_clab_mcp.errors import RequestError
from engulf_clab_mcp.protocol import parse_request


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    def test_rejects_untyped_or_unknown_shape(self) -> None:
        with self.assertRaisesRegex(RequestError, "request id"):
            parse_request({"version": 1, "id": "bad id", "method": "labs.list"})
        with self.assertRaisesRegex(RequestError, "params"):
            parse_request({"version": 1, "id": "id", "method": "labs.list", "params": []})

    async def test_bridge_maps_one_socket_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "service.sock"

            async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                request = json.loads(await reader.readline())
                response = {
                    "version": 1,
                    "id": request["id"],
                    "ok": True,
                    "result": {"method": request["method"]},
                }
                writer.write(json.dumps(response).encode("utf-8") + b"\n")
                await writer.drain()
                writer.close()

            try:
                server = await asyncio.start_unix_server(handler, path=str(path))
            except PermissionError:
                self.skipTest("the execution sandbox does not permit Unix socket creation")
            try:
                response = await UnixRpcClient(path).call("labs.list", {})
            finally:
                server.close()
                await server.wait_closed()
            self.assertEqual(response, {"ok": True, "result": {"method": "labs.list"}})

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "official MCP SDK is not installed")
    async def test_bridge_registers_the_supported_mcp_tools(self) -> None:
        from engulf_clab_mcp.bridge import create_server

        server = create_server(Path("/tmp/eclab-mcp.sock"))
        tools = await server.list_tools()
        self.assertEqual(
            {tool.name for tool in tools},
            {
                "eclab_deploy",
                "eclab_destroy",
                "eclab_diagnostics",
                "eclab_job_cancel",
                "eclab_job_logs",
                "eclab_job_status",
                "eclab_list_jobs",
                "eclab_list_labs",
                "eclab_node_logs",
                "eclab_status",
                "eclab_validate",
            },
        )


if __name__ == "__main__":
    unittest.main()
