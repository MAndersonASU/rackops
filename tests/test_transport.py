"""Real HTTP + redis-py sockets, simulated Redis server: NOT Redis integration."""

import os
import socket
import subprocess
import sys
import threading
import time

import fakeredis
import httpx

from rackops.checker import probe


def test_real_http_and_redis_protocol_fixture_recovery():
    server = fakeredis.TcpFakeServer(("127.0.0.1", 0), server_type="redis")
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        reports = []
        # A bound, non-listening socket gives a deterministic unavailable endpoint.
        with socket.socket() as unavailable:
            unavailable.bind(("127.0.0.1", 0))
            ports = [
                server.server_address[1],
                unavailable.getsockname()[1],
                server.server_address[1],
            ]
            for redis_port in ports:
                with socket.socket() as reservation:
                    reservation.bind(("127.0.0.1", 0))
                    api_port = reservation.getsockname()[1]
                env = {
                    **os.environ,
                    "RACKOPS_REDIS_HOST": "127.0.0.1",
                    "RACKOPS_REDIS_PORT": str(redis_port),
                }
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "rackops.app:create_app",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(api_port),
                        "--no-access-log",
                    ],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                try:
                    with httpx.Client(
                        base_url=f"http://127.0.0.1:{api_port}", timeout=2, trust_env=False
                    ) as client:
                        deadline = time.monotonic() + 15
                        while time.monotonic() < deadline:
                            assert process.poll() is None, "API process failed to start"
                            try:
                                if client.get("/livez").status_code == 200:
                                    break
                            except httpx.HTTPError:
                                pass
                            time.sleep(0.1)
                        else:
                            raise AssertionError("API startup timed out")
                        reports.append(probe(client, duration=2, rate=5))
                        assert client.get("/livez").status_code == 200
                        expected = 503 if redis_port == ports[1] else 200
                        assert client.get("/readyz").status_code == expected
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
        assert [r["passed"] for r in reports] == [True, False, True]
        assert reports[1]["successes"] == 0
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
