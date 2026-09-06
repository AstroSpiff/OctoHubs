"""
ASGI entry point for FastAPI.
Run with: uvicorn asgi:app --host 0.0.0.0 --port 5050 --no-proxy-headers
"""

from runtime.app_setup import create_app

app = create_app()
