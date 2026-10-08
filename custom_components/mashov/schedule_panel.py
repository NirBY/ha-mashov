"""Admin-only interactive schedule editor; commits one complete draft atomically."""

from contextlib import suppress
from hashlib import sha256
import json
from pathlib import Path

from homeassistant import config_entries
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import KEY_HASS_USER, HomeAssistantView, StaticPathConfig
from homeassistant.core import callback
from homeassistant.data_entry_flow import UnknownFlow
from homeassistant.helpers.translation import async_get_translations
import voluptuous as vol

from .const import DOMAIN
from .data_schedule import (
    CONF_DATA_SCHEDULES,
    CONF_STUDENT_SCHEDULES,
    DATA_SCHEDULES_SCHEMA,
    SCHEDULE_SCHEMA,
    STUDENT_SCHEDULES_SCHEMA,
    normalized_schedule,
)
from .data_selection import DATA_KEYS, enabled_data


def revision(entry):
    """Detect concurrent options changes without returning the options themselves."""
    return sha256(json.dumps(dict(entry.options), sort_keys=True, default=str).encode()).hexdigest()


def save_schedules(hass, entry_id, expected_revision, general, overrides, student_schedules=None):
    """Validate the complete draft before changing any stored settings."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ValueError("unknown_entry")
    if revision(entry) != expected_revision:
        raise ValueError("settings_changed")
    general = SCHEDULE_SCHEMA(general)
    overrides = DATA_SCHEDULES_SCHEMA(overrides)
    options = {**entry.options, **general, CONF_DATA_SCHEDULES: overrides}
    if student_schedules is not None:
        options[CONF_STUDENT_SCHEDULES] = STUDENT_SCHEDULES_SCHEMA(student_schedules)
    options.pop("schedule_day", None)
    hass.config_entries.async_update_entry(entry, options=options)
    return revision(entry)


@websocket_api.websocket_command(
    {vol.Required("type"): "mashov/schedules/get", vol.Optional("language", default="en"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_get(hass, connection, msg):
    labels = await async_get_translations(hass, msg["language"], "selector", {DOMAIN})
    config_labels = await async_get_translations(hass, msg["language"], "config", {DOMAIN})
    connection.send_result(
        msg["id"],
        {
            "ui": {
                key.removeprefix(f"component.{DOMAIN}.selector.schedule_editor.options."): value
                for key, value in labels.items()
                if key.startswith(f"component.{DOMAIN}.selector.schedule_editor.options.")
            },
            "errors": {
                key.removeprefix(f"component.{DOMAIN}.config.error."): value
                for key, value in config_labels.items()
                if key.startswith(f"component.{DOMAIN}.config.error.")
            },
            "default_general": normalized_schedule({}),
            "entries": [
                {
                    "entry_id": entry.entry_id,
                    "title": entry.title,
                    "revision": revision(entry),
                    "general": normalized_schedule(entry.options),
                    "overrides": dict(entry.options.get(CONF_DATA_SCHEDULES) or {}),
                    "enabled": sorted(enabled_data(entry.options)),
                    "student_schedules": dict(entry.options.get(CONF_STUDENT_SCHEDULES) or {}),
                    "students": list(
                        (hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("coordinator").data or {}).get(
                            "students", []
                        )
                    )
                    if hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("coordinator")
                    else [],
                }
                for entry in hass.config_entries.async_entries(DOMAIN)
            ],
            "datasets": [
                {"key": key, "label": labels.get(f"component.{DOMAIN}.selector.enabled_data.options.{key}", key)}
                for key in DATA_KEYS
            ],
            "yaml_schedule": {
                key: value
                for key, value in (hass.data.get(DOMAIN, {}).get("yaml_options") or {}).items()
                if key.startswith("schedule_")
            },
            "timezone": hass.config.time_zone,
        },
    )


async def create_hub(hass, payload):
    """Run the normal registration/authentication flow and commit schedules with the hub."""
    general = SCHEDULE_SCHEMA(payload["general"])
    general["schedule_days"] = [str(day) for day in general["schedule_days"]]
    overrides = DATA_SCHEDULES_SCHEMA(payload["overrides"])
    manager = hass.config_entries.flow
    form = await manager.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    flow_id = form["flow_id"]
    try:
        result = await manager.async_configure(
            flow_id,
            {
                "username": payload["username"],
                "password": payload["password"],
                "school_name": payload["school_name"],
                "enabled_data": payload["enabled_data"],
                **general,
                CONF_DATA_SCHEDULES: overrides,
            },
        )
        if result["type"] == "create_entry":
            return {"created": True, "entry_id": result["result"].entry_id, "revision": revision(result["result"])}
        if result["type"] == "abort":
            return {"created": False, "errors": [result["reason"]]}
        if result.get("step_id") == "pick_school":
            return {"created": False, "errors": ["choose_school_id"]}

        def codes(errors):
            return [
                code for value in errors.values() for code in (codes(value) if isinstance(value, dict) else [value])
            ]

        return {"created": False, "errors": codes(result.get("errors") or {}) or ["cannot_connect"]}
    finally:
        with suppress(UnknownFlow):
            manager.async_abort(flow_id)


REGISTRATION_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,
        vol.Required("school_name"): str,
        vol.Required("enabled_data"): [vol.In(DATA_KEYS)],
        vol.Required("general"): dict,
        vol.Required("overrides"): dict,
        vol.Optional("student_schedules"): dict,
    }
)


class HubRegistrationView(HomeAssistantView):
    """Credentials travel via authenticated HTTP, not WebSocket debug messages."""

    url = "/api/mashov/hub/register"
    name = "api:mashov:hub:register"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def post(self, request):
        user = request.get(KEY_HASS_USER)
        if user is None or not user.is_admin:
            return self.json_message("Administrator access required", status_code=403)
        try:
            payload = REGISTRATION_SCHEMA(await request.json())
            result = await create_hub(self.hass, payload)
        except vol.Invalid:
            return self.json({"created": False, "errors": ["invalid_data_schedule"]})
        except (ValueError, TypeError):
            return self.json_message("Invalid request", status_code=400)
        return self.json(result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "mashov/schedules/save",
        vol.Required("entry_id"): str,
        vol.Required("revision"): str,
        vol.Required("general"): dict,
        vol.Required("overrides"): dict,
        vol.Optional("student_schedules"): dict,
    }
)
@websocket_api.require_admin
@callback
def websocket_save(hass, connection, msg):
    try:
        saved_revision = save_schedules(
            hass, msg["entry_id"], msg["revision"], msg["general"], msg["overrides"], msg.get("student_schedules")
        )
    except vol.Invalid:
        connection.send_error(msg["id"], "invalid_schedule", "Enter a valid time, interval and weekly days.")
    except ValueError as error:
        connection.send_error(msg["id"], str(error), str(error))
    else:
        connection.send_result(msg["id"], {"revision": saved_revision})


async def async_setup_panel(hass):
    script_path = Path(__file__).with_name("schedule-editor.js")
    script_revision = sha256(script_path.read_bytes()).hexdigest()[:12]
    websocket_api.async_register_command(hass, websocket_get)
    websocket_api.async_register_command(hass, websocket_save)
    hass.http.register_view(HubRegistrationView(hass))
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                "/mashov-schedule-editor.js", str(Path(__file__).with_name("schedule-editor.js")), cache_headers=False
            )
        ]
    )
    frontend.add_extra_js_url(hass, f"/mashov-schedule-editor.js?v={script_revision}")
    hass.data[DOMAIN]["inline_schedule_editor"] = True
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path="mashov-schedules",
        webcomponent_name="mashov-schedule-editor",
        module_url=f"/mashov-schedule-editor.js?v={script_revision}",
        require_admin=True,
        embed_iframe=False,
    )
