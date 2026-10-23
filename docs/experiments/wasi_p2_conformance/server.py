"""The server of the http script: the routes of tests/test_wasi_p2_http.py. Prints its port, then serves until it is killed."""

import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
from test_wasi_p2_http import respond  # noqa: E402

listener = socket.socket()
listener.bind(("127.0.0.1", 0))
listener.listen(16)
port = listener.getsockname()[1]
print(port, flush=True)
while True:
    conn, _ = listener.accept()
    threading.Thread(target=respond, args=(conn, port, False), daemon=True).start()
