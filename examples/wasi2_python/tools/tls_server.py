"""A local HTTPS server with a self-signed certificate, serving a directory (a PEP 503 index for pip, or plain files).

tls_server.py DIR PORT      # writes DIR/cert.pem, DIR/key.pem; serves DIR
"""

import functools
import http.server
import ssl
import subprocess
import sys

d, port = sys.argv[1], int(sys.argv[2])
subprocess.run(
    [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        f"{d}/key.pem",
        "-out",
        f"{d}/cert.pem",
        "-days",
        "2",
        "-subj",
        "/CN=localhost",
        "-addext",
        "subjectAltName=DNS:localhost,IP:127.0.0.1",
    ],
    check=True,
    capture_output=True,
)


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


c = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
c.load_cert_chain(f"{d}/cert.pem", f"{d}/key.pem")
s = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(H, directory=d))
s.socket = c.wrap_socket(s.socket, server_side=True)
s.serve_forever()
