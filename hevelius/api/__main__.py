"""python -m hevelius.api"""
import argparse

from hevelius.api import app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hevelius REST API (Flask dev server)")
    parser.add_argument("--host", default="127.0.0.1", help="Host/IP to listen on (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5001, help="Port to listen on (default: 5001)")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    app.run(host=args.host, port=args.port, debug=args.debug)
