from __future__ import annotations

import logging

from homeassistant import config_entries  # type: ignore[import-not-found]
from homeassistant.core import callback  # type: ignore[import-not-found]
from homeassistant.data_entry_flow import FlowResult  # type: ignore[import-not-found]
from homeassistant.helpers.selector import (  # type: ignore[import-not-found]
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol  # type: ignore[import-not-found]

_LOGGER = logging.getLogger(__name__)

import contextlib

from .const import (
    CONF_API_BASE,
    CONF_HOMEWORK_DAYS_BACK,
    CONF_HOMEWORK_DAYS_FORWARD,
    CONF_MAX_ITEMS_IN_ATTRIBUTES,
    CONF_PASSWORD,
    CONF_SCHEDULE_DAY,
    CONF_SCHEDULE_DAYS,
    CONF_SCHEDULE_INTERVAL,
    CONF_SCHEDULE_TIME,
    CONF_SCHEDULE_TYPE,
    CONF_SCHOOL_ID,
    CONF_SCHOOL_NAME,
    CONF_USERNAME,
    DEFAULT_API_BASE,
    DEFAULT_HOMEWORK_DAYS_BACK,
    DEFAULT_HOMEWORK_DAYS_FORWARD,
    DEFAULT_MAX_ITEMS_IN_ATTRIBUTES,
    DEFAULT_SCHEDULE_DAY,
    DEFAULT_SCHEDULE_INTERVAL,
    DEFAULT_SCHEDULE_TIME,
    DEFAULT_SCHEDULE_TYPE,
    DOMAIN,
)
from .mashov_client import MashovAuthError, MashovClient, MashovError


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._cached_user = None
        self._school_choices = None
        self._catalog_options = None  # list of {"value": semel, "label": display}

    async def _load_schools_catalog(self):
        """Load schools catalog in a separate task to avoid blocking MainThread"""
        tmp = MashovClient(
            school_id="placeholder",
            year=None,
            username="",
            password="",
            api_base=DEFAULT_API_BASE,
        )
        try:
            await tmp.async_open_session()
            return await tmp.async_fetch_schools_catalog(None)
        finally:
            await tmp.async_close()

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors = {}

        # Try to load catalog for dropdown (no login required)
        if self._catalog_options is None:
            try:
                # Load catalog directly
                catalog = await self._load_schools_catalog()

                if catalog and len(catalog) > 0:
                    # Sort by name for better autocomplete - handle None values
                    sorted_catalog = sorted(catalog, key=lambda x: (x.get("name") or "").lower())
                    self._catalog_options = []
                    for it in sorted_catalog:
                        if it.get("semel") and it.get("name"):
                            name = it.get("name", "?")
                            semel = int(it["semel"])
                            # Do not separate city; show the exact name
                            label = f"{name} ({semel})"
                            self._catalog_options.append({"value": semel, "label": label})
                    # Limit to first 50 schools for better dropdown performance
                    if len(self._catalog_options) > 50:
                        self._catalog_options = self._catalog_options[:50]
            except Exception as e:
                _LOGGER.debug("Failed to load schools catalog: %s", e)
                self._catalog_options = []

        # Build schema with text input and autocomplete
        if self._catalog_options and len(self._catalog_options) > 0:
            _LOGGER.debug("Created %d autocomplete options", len(self._catalog_options))

            # Create simple autocomplete list
            autocomplete_list = [opt["label"] for opt in self._catalog_options]

            schema = vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(
                        CONF_SCHOOL_NAME, description={"suggested_value": "", "autocomplete": autocomplete_list}
                    ): str,
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_SCHOOL_NAME, description={"suggested_value": ""}): str,  # name or semel
                }
            )

        if user_input is not None:
            # Determine school id from autocomplete or manual input
            school_raw = user_input[CONF_SCHOOL_NAME].strip()
            _LOGGER.debug("School input: %s", school_raw)

            if school_raw.isdigit():
                # Direct semel number
                user_input[CONF_SCHOOL_ID] = int(school_raw)
                _LOGGER.debug("Using direct semel: %s", user_input[CONF_SCHOOL_ID])
            else:
                # Try to extract semel from autocomplete format: "School Name – City (123456)"
                import re

                semel_match = re.search(r"\((\d+)\)$", school_raw)
                if semel_match:
                    user_input[CONF_SCHOOL_ID] = int(semel_match.group(1))
                    _LOGGER.debug("Extracted semel from autocomplete: %s", user_input[CONF_SCHOOL_ID])
                else:
                    # Search for schools without trying to authenticate
                    tmp_client = MashovClient(
                        school_id="placeholder",
                        year=None,
                        username="",
                        password="",
                        api_base=DEFAULT_API_BASE,
                    )
                    try:
                        await tmp_client.async_open_session()
                        results = await tmp_client.async_search_schools(school_raw, None)
                        await tmp_client.async_close()

                        if not results:
                            errors["base"] = "school_not_found"
                            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

                        if len(results) > 1:
                            self._cached_user = user_input
                            # Create choices with school name and semel
                            self._school_choices = {}
                            for r in results:
                                name = r.get("name", "Unknown School")
                                semel = r.get("semel")
                                if semel:
                                    label = f"{name} ({semel})"
                                    self._school_choices[label] = int(semel)
                            _LOGGER.debug(
                                "Created %d school choices: %s",
                                len(self._school_choices),
                                list(self._school_choices.keys()),
                            )
                            return await self.async_step_pick_school()

                        user_input[CONF_SCHOOL_ID] = int(results[0]["semel"])
                        # Cache plain school name for title
                        self._cached_user = dict(user_input)
                        self._cached_user[CONF_SCHOOL_NAME] = results[0].get("name") or str(user_input[CONF_SCHOOL_ID])
                    except Exception as e:
                        _LOGGER.error("Error searching for schools: %s", e)
                        errors["base"] = "cannot_connect"
                        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

            # Validate login; client will fetch all kids
            client = MashovClient(
                school_id=user_input[CONF_SCHOOL_ID],
                year=None,
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
            )
            try:
                # Run authentication directly
                await client.async_init(self.hass)
            except MashovAuthError as e:
                _LOGGER.error("Authentication error: %s", e)
                errors["base"] = "auth"
            except MashovError as e:
                _LOGGER.error("Mashov error: %s", e)
                errors["base"] = "cannot_connect"
            except Exception as e:
                _LOGGER.error("Unexpected error during authentication: %s", e)
                errors["base"] = "cannot_connect"
            else:
                await client.async_close()
                # Get school name from the cached data or use semel as fallback
                if self._cached_user and CONF_SCHOOL_NAME in self._cached_user:
                    school_name = self._cached_user[CONF_SCHOOL_NAME]
                else:
                    school_name = user_input.get(CONF_SCHOOL_NAME, str(user_input[CONF_SCHOOL_ID]))
                school_semel = user_input[CONF_SCHOOL_ID]
                _LOGGER.debug("Creating entry with title: %s (%s)", school_name, school_semel)
                # Save school name in data for later use (e.g., title updates)
                user_input[CONF_SCHOOL_NAME] = school_name
                return self.async_create_entry(title=f"{school_name} ({school_semel})", data=user_input)

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_pick_school(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            # Convert string value back to int
            selected_semel = int(user_input["selected_school"])
            self._cached_user[CONF_SCHOOL_ID] = selected_semel

            # Find the school name from the choices (extract plain name without city/semel)
            school_name = None
            for label, semel in self._school_choices.items():
                if semel == selected_semel:
                    # label format: "Name – City (Semel)"
                    school_name = label.split(" – ")[0].split(" (")[0]
                    break

            self._cached_user[CONF_SCHOOL_NAME] = school_name or str(selected_semel)
            return await self.async_step_user(self._cached_user)

        # Convert choices to SelectSelector format - values must be strings
        options = [{"value": str(semel), "label": label} for label, semel in self._school_choices.items()]

        schema = vol.Schema(
            {
                vol.Required("selected_school"): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        mode=SelectSelectorMode.DROPDOWN,
                        multiple=False,
                    )
                )
            }
        )
        return self.async_show_form(step_id="pick_school", data_schema=schema, errors=errors)

    # Ensure HA can discover options flow via the ConfigFlow class (for cores that expect it)
    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None) -> FlowResult:
        errors = {}
        _LOGGER.debug(
            "Options flow step_init called (entry_id=%s). user_input=%s",
            getattr(self.config_entry, "entry_id", ""),
            user_input,
        )
        if user_input is not None:
            errors = {}
            # Validate schedule_time format if present
            import re
            time_val = user_input.get(CONF_SCHEDULE_TIME, "")
            if time_val and not re.match(r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$", time_val):
                errors[CONF_SCHEDULE_TIME] = "invalid_time_format"
            
            if not errors:
                # Normalize: accept both legacy single day and new multi-days selector
            normalized = dict(user_input)
            try:
                if CONF_SCHEDULE_DAYS in normalized:
                    raw_days = normalized.get(CONF_SCHEDULE_DAYS) or []
                    casted = []
                    for v in raw_days:
                        with contextlib.suppress(Exception):
                            casted.append(max(0, min(6, int(v))))
                    if casted:
                        normalized[CONF_SCHEDULE_DAYS] = sorted(set(casted))
                # If missing multi-days but legacy exists, promote
                if CONF_SCHEDULE_DAYS not in normalized and CONF_SCHEDULE_DAY in normalized:
                    try:
                        d = int(normalized.get(CONF_SCHEDULE_DAY))
                    except Exception:
                        d = DEFAULT_SCHEDULE_DAY
                    normalized[CONF_SCHEDULE_DAYS] = [max(0, min(6, d))]
                # Drop legacy key
                if CONF_SCHEDULE_DAYS in normalized and CONF_SCHEDULE_DAY in normalized:
                    normalized.pop(CONF_SCHEDULE_DAY, None)
            except Exception as e:
                _LOGGER.debug("Options normalization failed: %s", e)

            if not errors:
                _LOGGER.info(
                    "Options submitted for '%s' (id=%s): %s",
                    getattr(self.config_entry, "title", ""),
                    getattr(self.config_entry, "entry_id", ""),
                    normalized,
                )
                return self.async_create_entry(title="", data=normalized)

        current_options = dict(self.config_entry.options or {})
        _LOGGER.debug("Building options schema from current options: %s", current_options)

        options = {
            CONF_HOMEWORK_DAYS_BACK: self.config_entry.options.get(CONF_HOMEWORK_DAYS_BACK, DEFAULT_HOMEWORK_DAYS_BACK),
            CONF_HOMEWORK_DAYS_FORWARD: self.config_entry.options.get(
                CONF_HOMEWORK_DAYS_FORWARD, DEFAULT_HOMEWORK_DAYS_FORWARD
            ),
            CONF_API_BASE: self.config_entry.options.get(CONF_API_BASE, DEFAULT_API_BASE),
            CONF_SCHEDULE_TYPE: self.config_entry.options.get(CONF_SCHEDULE_TYPE, DEFAULT_SCHEDULE_TYPE),
            CONF_SCHEDULE_TIME: self.config_entry.options.get(CONF_SCHEDULE_TIME, DEFAULT_SCHEDULE_TIME),
            CONF_SCHEDULE_DAY: self.config_entry.options.get(CONF_SCHEDULE_DAY, DEFAULT_SCHEDULE_DAY),
            CONF_SCHEDULE_DAYS: self.config_entry.options.get(CONF_SCHEDULE_DAYS, [DEFAULT_SCHEDULE_DAY]),
            CONF_SCHEDULE_INTERVAL: self.config_entry.options.get(CONF_SCHEDULE_INTERVAL, DEFAULT_SCHEDULE_INTERVAL),
            CONF_MAX_ITEMS_IN_ATTRIBUTES: self.config_entry.options.get(
                CONF_MAX_ITEMS_IN_ATTRIBUTES, DEFAULT_MAX_ITEMS_IN_ATTRIBUTES
            ),
        }
        _LOGGER.debug("Options defaults resolved: %s", options)
        schema = vol.Schema(
            {
                vol.Optional(CONF_HOMEWORK_DAYS_BACK, default=options[CONF_HOMEWORK_DAYS_BACK]): vol.All(
                    int, vol.Range(min=0, max=60)
                ),
                vol.Optional(CONF_HOMEWORK_DAYS_FORWARD, default=options[CONF_HOMEWORK_DAYS_FORWARD]): vol.All(
                    int, vol.Range(min=1, max=120)
                ),
                vol.Optional(CONF_API_BASE, default=options[CONF_API_BASE]): str,
                vol.Optional(CONF_SCHEDULE_TYPE, default=options[CONF_SCHEDULE_TYPE]): vol.In(
                    ["daily", "weekly", "interval"]
                ),
                vol.Optional(CONF_SCHEDULE_TIME, default=options[CONF_SCHEDULE_TIME]): str,
                # Hide legacy single-day field by not including it in the schema
                # Multi days selector via HA SelectSelector (multiple)
                vol.Optional(CONF_SCHEDULE_DAYS, default=[str(d) for d in options[CONF_SCHEDULE_DAYS]]): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": "0", "label": "Monday"},
                            {"value": "1", "label": "Tuesday"},
                            {"value": "2", "label": "Wednesday"},
                            {"value": "3", "label": "Thursday"},
                            {"value": "4", "label": "Friday"},
                            {"value": "5", "label": "Saturday"},
                            {"value": "6", "label": "Sunday"},
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                        multiple=True,
                    )
                ),
                vol.Optional(CONF_SCHEDULE_INTERVAL, default=options[CONF_SCHEDULE_INTERVAL]): vol.All(
                    int, vol.Range(min=5, max=1440)
                ),
                vol.Optional(CONF_MAX_ITEMS_IN_ATTRIBUTES, default=options[CONF_MAX_ITEMS_IN_ATTRIBUTES]): vol.All(
                    int, vol.Range(min=10, max=500)
                ),
            }
        )
        _LOGGER.debug(
            "Options schema built for entry '%s' (id=%s)",
            getattr(self.config_entry, "title", ""),
            getattr(self.config_entry, "entry_id", ""),
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)


# Backward/compatibility helper: expose options flow factory from this module as well
@callback
def async_get_options_flow(config_entry: config_entries.ConfigEntry):
    return OptionsFlowHandler()
