"""
Root conftest — sets required environment variables before any app module is
imported so that pydantic-settings can instantiate the Settings singleton
during test collection without a real .env file.
"""
import os

os.environ.setdefault("GOOGLE_MAPS_API_KEY", "test-key-not-used-in-tests")
