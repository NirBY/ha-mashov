"""Serve the bundled homework card from the integration so upgrades keep it available."""

from hashlib import sha256
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig


async def async_setup_dashboard_frontend(hass):
    for name in ("homework-card", "weekly-card"):
        path = Path(__file__).with_name(f"{name}.js")
        revision = sha256(await hass.async_add_executor_job(path.read_bytes)).hexdigest()[:12]
        url = f"/mashov-{name}.js"
        await hass.http.async_register_static_paths([StaticPathConfig(url, str(path), cache_headers=False)])
        frontend.add_extra_js_url(hass, f"{url}?v={revision}")
