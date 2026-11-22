"""The bundled checklist loads from installed integration files with a revision URL."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from custom_components.mashov.dashboard_frontend import async_setup_dashboard_frontend


async def test_registers_bundled_homework_card(hass, monkeypatch):
    http = SimpleNamespace(async_register_static_paths=AsyncMock())
    monkeypatch.setattr(hass, "http", http, raising=False)
    add_script = Mock()
    monkeypatch.setattr("custom_components.mashov.dashboard_frontend.frontend.add_extra_js_url", add_script)
    await async_setup_dashboard_frontend(hass)
    for call, script, name in zip(
        http.async_register_static_paths.call_args_list,
        add_script.call_args_list,
        ("homework-card", "weekly-card"),
        strict=True,
    ):
        config = call.args[0][0]
        assert config.url_path == f"/mashov-{name}.js"
        assert Path(config.path).is_file()
        assert config.cache_headers is False
        assert script.args[1].startswith(f"/mashov-{name}.js?v=")
