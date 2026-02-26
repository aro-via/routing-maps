import os
import pytest
from unittest.mock import patch


def test_max_stops_per_route_default():
    """Settings default MAX_STOPS_PER_ROUTE is 25."""
    with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
        from importlib import reload
        import app.config as config_module
        reload(config_module)
        assert config_module.settings.MAX_STOPS_PER_ROUTE == 25


def test_settings_defaults():
    """All default values are set correctly."""
    with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
        from importlib import reload
        import app.config as config_module
        reload(config_module)
        s = config_module.settings
        assert s.REDIS_HOST == "localhost"
        assert s.REDIS_PORT == 6379
        assert s.REDIS_TTL_SECONDS == 1800
        assert s.MAX_OPTIMIZATION_SECONDS == 10
        assert s.ENV == "development"
        assert s.LOG_LEVEL == "INFO"


def test_settings_override_via_env():
    """Environment variables override defaults."""
    overrides = {
        "GOOGLE_MAPS_API_KEY": "my-api-key",
        "MAX_STOPS_PER_ROUTE": "10",
        "REDIS_PORT": "6380",
    }
    with patch.dict(os.environ, overrides, clear=False):
        from importlib import reload
        import app.config as config_module
        reload(config_module)
        s = config_module.settings
        assert s.GOOGLE_MAPS_API_KEY == "my-api-key"
        assert s.MAX_STOPS_PER_ROUTE == 10
        assert s.REDIS_PORT == 6380


def test_settings_singleton_exported():
    """The module exports a `settings` singleton instance."""
    with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False):
        from importlib import reload
        import app.config as config_module
        reload(config_module)
        from app.config import Settings
        assert isinstance(config_module.settings, Settings)
