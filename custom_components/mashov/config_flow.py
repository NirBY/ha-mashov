"""Config and options flows for the Mashov integration.

Setup ("user" step) asks for the parent's username, password and school. The
school field accepts a semel (Israeli school id), an autocomplete label ending
in "(semel)", or free text that is searched in the public school catalog. When
the search matches several schools, the "pick_school" step shows a dropdown and
then re-enters the user step with the chosen semel.

One config entry represents one parent account at one school (all of that
account's children are discovered after login). Its unique_id is
"<semel>_<lowercased username>".

The options flow edits polling/schedule options and can also change the
username/password, which live in entry.data rather than entry.options.
"""

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
    CONF_YEAR,
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
from .data_selection import (
    CONF_ENABLED_DATA,
    CONF_MAILBOX_FULL_CONTENT,
    CONF_MAILBOX_LIMIT,
    DATA_KEYS,
    DEFAULT_MAILBOX_LIMIT,
    enabled_data,
    merge_selection_options,
)
from .mashov_client import MashovAuthError, MashovClient, MashovError


def _data_fields(selected, full_content=False, limit=DEFAULT_MAILBOX_LIMIT):
    """Shared explicit choices for new hubs and existing hubs' Configure form."""
    return {
        vol.Optional(CONF_ENABLED_DATA, default=list(selected)): SelectSelector(
            SelectSelectorConfig(
                options=list(DATA_KEYS), multiple=True, mode=SelectSelectorMode.DROPDOWN, translation_key="enabled_data"
            )
        ),
        vol.Optional(CONF_MAILBOX_FULL_CONTENT, default=full_content): bool,
        vol.Optional(CONF_MAILBOX_LIMIT, default=limit): vol.All(int, vol.Range(min=1, max=50)),
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Initial setup flow: credentials + school, validated by a real login."""

    VERSION = 1

    def __init__(self):
        # User input carried across the pick_school step (plus the resolved school name).
        self._cached_user = None
        # label -> semel for the pick_school dropdown when a name search is ambiguous.
        self._school_choices = None
        self._catalog_options = None  # list of {"value": semel, "label": display}

    async def _load_schools_catalog(self):
        """Fetch the public school catalog; no login is needed.

        Uses a throwaway client with placeholder credentials that is always closed.
        """
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
        """Collect credentials and school, resolve the semel, log in and create the entry.

        Also called by async_step_pick_school with the cached input, which then
        already contains CONF_SCHOOL_ID.
        """
        errors = {}

        # Try to load catalog for dropdown (no login required). Loaded once per flow;
        # a failure leaves an empty list so the form falls back to plain text input.
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
                            # Do not separate city; show the exact name. The trailing
                            # "(semel)" is what the submit handler parses back out.
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

        # Credentials discover the account's students; only selected data is fetched.
        submitted = user_input or {}
        schema = schema.extend(
            _data_fields(
                submitted.get(CONF_ENABLED_DATA, []),
                submitted.get(CONF_MAILBOX_FULL_CONTENT, False),
                submitted.get(CONF_MAILBOX_LIMIT, DEFAULT_MAILBOX_LIMIT),
            )
        )

        if user_input is not None:
            if user_input.get(CONF_MAILBOX_FULL_CONTENT) and "mailbox" not in user_input.get(CONF_ENABLED_DATA, []):
                errors[CONF_MAILBOX_FULL_CONTENT] = "mailbox_required"
                return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
            # Determine school id from autocomplete or manual input
            school_raw = user_input[CONF_SCHOOL_NAME].strip()
            _LOGGER.debug("School input: %s", school_raw)

            if CONF_SCHOOL_ID in user_input:
                # Already chosen in the pick_school step; searching the plain name again could
                # match several schools and loop back to the picker (or pick a different school).
                pass
            elif school_raw.isdigit():
                # Direct semel number
                user_input[CONF_SCHOOL_ID] = int(school_raw)
                _LOGGER.debug("Using direct semel: %s", user_input[CONF_SCHOOL_ID])
            else:
                # Try to extract semel from autocomplete format: "School Name (123456)"
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
                        try:
                            await tmp_client.async_open_session()
                            results = await tmp_client.async_search_schools(school_raw, None)
                        finally:
                            await tmp_client.async_close()

                        if not results:
                            errors["base"] = "school_not_found"
                            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

                        if len(results) > 1:
                            # Ambiguous name: remember the input and let the user choose.
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

            # Validate login; client will fetch all kids. The client is only used for
            # validation and is closed right away; the coordinator creates its own.
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
            finally:
                await client.async_close()
            if not errors:
                # Duplicate detection. Legacy entries have no account-based unique_id;
                # credentials may also have changed since a newer entry received its
                # unique_id. So compare the stored school + username (case-insensitive)
                # first, then fall back to the unique_id check below.
                for existing in self._async_current_entries():
                    if (
                        str(existing.data.get(CONF_SCHOOL_ID)) == str(user_input[CONF_SCHOOL_ID])
                        and str(existing.data.get(CONF_USERNAME, "")).strip().lower()
                        == user_input[CONF_USERNAME].strip().lower()
                    ):
                        return self.async_abort(reason="already_configured")
                await self.async_set_unique_id(
                    f"{user_input[CONF_SCHOOL_ID]}_{user_input[CONF_USERNAME].strip().lower()}"
                )
                self._abort_if_unique_id_configured()
                # Get school name from the cached data or use semel as fallback
                if self._cached_user and CONF_SCHOOL_NAME in self._cached_user:
                    school_name = self._cached_user[CONF_SCHOOL_NAME]
                else:
                    school_name = user_input.get(CONF_SCHOOL_NAME, str(user_input[CONF_SCHOOL_ID]))
                school_semel = user_input[CONF_SCHOOL_ID]
                _LOGGER.debug("Creating entry with title: %s (%s)", school_name, school_semel)
                # Save school name in data for later use (e.g., title updates)
                user_input[CONF_SCHOOL_NAME] = school_name
                selection = {
                    key: user_input.pop(key)
                    for key in (CONF_ENABLED_DATA, CONF_MAILBOX_FULL_CONTENT, CONF_MAILBOX_LIMIT)
                    if key in user_input
                }
                selection.setdefault(CONF_ENABLED_DATA, [])
                selection.setdefault(CONF_MAILBOX_FULL_CONTENT, False)
                return self.async_create_entry(
                    title=f"{school_name} ({school_semel})",
                    data=user_input,
                    options=merge_selection_options({}, selection),
                )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_pick_school(self, user_input=None) -> FlowResult:
        """Let the user choose among several schools matching the typed name.

        The choice is stored as CONF_SCHOOL_ID in the cached input, so the user
        step skips its name search instead of re-running it.
        """
        errors = {}
        if user_input is not None:
            # Convert string value back to int
            selected_semel = int(user_input["selected_school"])
            self._cached_user[CONF_SCHOOL_ID] = selected_semel

            # Find the school name from the choices (extract plain name without city/semel)
            school_name = None
            for label, semel in self._school_choices.items():
                if semel == selected_semel:
                    # Label format is "Name (Semel)"; the " – " split also strips a
                    # city suffix in case a label ever includes one.
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
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow: schedule/fetch options plus optional credential changes."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        """Return the entry, working on both older and newer HA cores.

        Newer cores provide config_entry on the base class (and raise if it isn't
        set up yet); older ones don't, so fall back to the entry passed in.
        """
        with contextlib.suppress(AttributeError, ValueError):
            return super().config_entry
        return self._config_entry

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Show the options form, or validate and save a submission.

        Username/password are moved out of the options into entry.data; an empty
        password field means "keep the current password".
        """
        errors = {}
        _LOGGER.debug(
            "Options flow step_init called (entry_id=%s). submitted=%s",
            getattr(self.config_entry, "entry_id", ""),
            user_input is not None,
        )
        if user_input is not None:
            errors = {}
            if user_input.get(CONF_MAILBOX_FULL_CONTENT) and "mailbox" not in user_input.get(
                CONF_ENABLED_DATA, enabled_data(self.config_entry.options)
            ):
                if "mailbox" in enabled_data(self.config_entry.options):
                    # Removing mailbox takes precedence over its old checked
                    # full-content box. Re-enabling starts with no read consent.
                    user_input = {**user_input, CONF_MAILBOX_FULL_CONTENT: False}
                else:
                    errors[CONF_MAILBOX_FULL_CONTENT] = "mailbox_required"
            # Validate schedule_time format if present
            import re

            time_val = user_input.get(CONF_SCHEDULE_TIME, "")
            if time_val and not re.match(r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?$", time_val):
                errors[CONF_SCHEDULE_TIME] = "invalid_time_format"

            # Validate API URL
            api_val = user_input.get(CONF_API_BASE, "").strip()
            if api_val and not (api_val.startswith("http://") or api_val.startswith("https://")):
                errors[CONF_API_BASE] = "invalid_api_url"

            # Refuse a username change that would duplicate another entry for the same school.
            proposed_username = str(user_input.get(CONF_USERNAME, "")).strip()
            if (
                proposed_username
                and proposed_username != self.config_entry.data.get(CONF_USERNAME)
                and any(
                    other.entry_id != self.config_entry.entry_id
                    and str(other.data.get(CONF_SCHOOL_ID)) == str(self.config_entry.data.get(CONF_SCHOOL_ID))
                    and str(other.data.get(CONF_USERNAME, "")).strip().lower() == proposed_username.lower()
                    for other in self.hass.config_entries.async_entries(DOMAIN)
                )
            ):
                errors["base"] = "already_configured"

            if not errors:
                # Normalize: accept both legacy single day and new multi-days selector.
                # Start from the existing options so keys not on the form are kept.
                normalized = merge_selection_options(self.config_entry.options, user_input)
                try:
                    if CONF_SCHEDULE_DAYS in normalized:
                        # The selector returns strings; store sorted unique ints clamped to 0-6.
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

                # Credentials belong in entry.data; pop them so they never end up in options.
                updated_data = dict(self.config_entry.data)
                new_username = str(normalized.pop(CONF_USERNAME, "")).strip()
                if new_username:
                    updated_data[CONF_USERNAME] = new_username

                new_password = str(normalized.pop(CONF_PASSWORD, "")).strip()
                if new_password:
                    updated_data[CONF_PASSWORD] = new_password

                # Move the entry to the unique_id matching the new username, unless another
                # entry (by unique_id or, for legacy entries, by school + username) already
                # represents that account; then keep the current unique_id to avoid a clash.
                candidate_id = f"{updated_data[CONF_SCHOOL_ID]}_{updated_data[CONF_USERNAME].strip().lower()}"
                duplicate = any(
                    other.entry_id != self.config_entry.entry_id
                    and (
                        other.unique_id == candidate_id
                        or (
                            str(other.data.get(CONF_SCHOOL_ID)) == str(updated_data[CONF_SCHOOL_ID])
                            and str(other.data.get(CONF_USERNAME, "")).strip().lower()
                            == updated_data[CONF_USERNAME].strip().lower()
                        )
                    )
                    for other in self.hass.config_entries.async_entries(DOMAIN)
                )
                if updated_data != dict(self.config_entry.data):
                    # Save credentials and options together so the update listener reloads once;
                    # the create_entry below then finds identical options and does not fire again.
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data=updated_data,
                        options=normalized,
                        unique_id=self.config_entry.unique_id if duplicate else candidate_id,
                    )
                    _LOGGER.info(
                        "Credentials updated for '%s' (id=%s)",
                        getattr(self.config_entry, "title", ""),
                        getattr(self.config_entry, "entry_id", ""),
                    )

                _LOGGER.info(
                    "Options submitted for '%s' (id=%s): %s",
                    getattr(self.config_entry, "title", ""),
                    getattr(self.config_entry, "entry_id", ""),
                    normalized,
                )
                return self.async_create_entry(title="", data=normalized)

        current_options = dict(self.config_entry.options)
        for key in (CONF_ENABLED_DATA, CONF_MAILBOX_FULL_CONTENT, CONF_MAILBOX_LIMIT):
            if user_input is not None and key in user_input:
                current_options[key] = user_input[key]
        _LOGGER.debug("Building options schema from current options: %s", current_options)

        options = {
            CONF_USERNAME: self.config_entry.data.get(CONF_USERNAME, ""),
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
        _LOGGER.debug("Options defaults resolved")
        schema = vol.Schema(
            {
                vol.Optional(CONF_USERNAME, default=options[CONF_USERNAME]): str,
                # Follow the current school year automatically. Defaults to on unless the
                # entry was set up with a fixed year in its data.
                vol.Optional(
                    "automatic_school_year",
                    default=current_options.get("automatic_school_year", not self.config_entry.data.get(CONF_YEAR)),
                ): bool,
                **_data_fields(
                    enabled_data(current_options),
                    current_options.get(CONF_MAILBOX_FULL_CONTENT, False),
                    current_options.get(CONF_MAILBOX_LIMIT, DEFAULT_MAILBOX_LIMIT),
                ),
                # Never prefilled with the stored password; leave empty to keep it.
                vol.Optional(CONF_PASSWORD, description={"suggested_value": ""}): str,
                vol.Optional(CONF_HOMEWORK_DAYS_BACK, default=options[CONF_HOMEWORK_DAYS_BACK]): vol.All(
                    int, vol.Range(min=0, max=60)
                ),
                vol.Optional(CONF_HOMEWORK_DAYS_FORWARD, default=options[CONF_HOMEWORK_DAYS_FORWARD]): vol.All(
                    int, vol.Range(min=1, max=120)
                ),
                vol.Optional(CONF_API_BASE, default=options[CONF_API_BASE]): str,
                vol.Optional(CONF_SCHEDULE_TYPE, default=options[CONF_SCHEDULE_TYPE]): SelectSelector(
                    SelectSelectorConfig(options=["daily", "weekly", "interval"], translation_key="schedule_type")
                ),
                vol.Optional(CONF_SCHEDULE_TIME, default=options[CONF_SCHEDULE_TIME]): str,
                # Hide legacy single-day field by not including it in the schema
                # Multi days selector via HA SelectSelector (multiple)
                vol.Optional(CONF_SCHEDULE_DAYS, default=[str(d) for d in options[CONF_SCHEDULE_DAYS]]): SelectSelector(
                    SelectSelectorConfig(
                        options=[str(d) for d in range(7)],
                        translation_key="schedule_days",
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
    return OptionsFlowHandler(config_entry)
