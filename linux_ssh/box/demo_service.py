"""A tiny HTTP service for the SSH smoke tests (standard library only).

GET /health     -> {"status": "ok"}
GET /api/hello  -> {"message": "hello"}
Every request is logged with its X-Request-ID, so a test can trace one request.
"""

import argparse
import configparser
import json
import logging
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROUTES = {"/health": {"status": "ok"}, "/api/hello": {"message": "hello"}}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        request_id = self.headers.get("X-Request-ID") or str(uuid.uuid4())
        body = ROUTES.get(self.path)
        status = 200 if body is not None else 404
        # Log BEFORE responding: once the client has its response, the log line is
        # already written, so a test can grep for it without waiting.
        logging.info("request_id=%s method=GET path=%s status=%d", request_id, self.path, status)

        payload = json.dumps(body if body is not None else {"error": "not found"}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Request-ID", request_id)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        pass  # replaced by the structured line in do_GET


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    config = configparser.ConfigParser()
    config.read(parser.parse_args().config)

    logging.basicConfig(
        filename=config["server"]["log_file"],
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    port = int(config["server"]["port"])
    logging.info("starting on port %d", port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
