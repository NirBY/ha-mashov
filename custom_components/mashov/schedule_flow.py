"""Shared draft/overview/editor navigation for setup and options flows."""

from homeassistant.data_entry_flow import section
from homeassistant.helpers.http import current_request
from homeassistant.helpers.selector import Selector, SelectSelector, SelectSelectorConfig, SelectSelectorMode
from homeassistant.helpers.translation import async_get_translations
import voluptuous as vol

from .const import CONF_SCHEDULE_DAYS, CONF_SCHEDULE_INTERVAL, CONF_SCHEDULE_TIME, CONF_SCHEDULE_TYPE, DOMAIN
from .data_schedule import (
    CONF_DATA_SCHEDULES,
    CONF_STUDENT_SCHEDULES,
    DATA_SCHEDULES_SCHEMA,
    SCHEDULE_SCHEMA,
    STUDENT_SCHEDULES_SCHEMA,
    effective_schedule,
    normalized_schedule,
)
from .data_selection import DATA_KEYS, enabled_data

FORM_SECTIONS = {
    "data": {"enabled_data", "mailbox_full_content", "mailbox_limit"},
    "refresh": {"schedule_type", "schedule_time", "schedule_days", "schedule_interval", "edit_data_schedules"},
    "account": {"username", "password", "school_name", "automatic_school_year"},
    "advanced": {"homework_days_back", "homework_days_forward", "api_base", "max_items_in_attributes"},
}


class ScheduleEditorSelector(Selector):
    """Inline web component rendered by HA's normal selector host."""

    selector_type = "mashov_schedule"
    CONFIG_SCHEMA = vol.Schema({vol.Optional("entry_id"): str, vol.Optional("setup", default=False): bool})

    def __call__(self, value):
        return vol.Schema(
            {
                vol.Required("general"): SCHEDULE_SCHEMA,
                vol.Required("overrides"): DATA_SCHEDULES_SCHEMA,
                vol.Optional(CONF_STUDENT_SCHEDULES, default={}): STUDENT_SCHEDULES_SCHEMA,
            }
        )(value)


class GroupedSettingsSchema(vol.Schema):
    """Render native sections while keeping the existing flat flow contract."""

    def __init__(self, schema, *, setup=False, errors=None, inline=None):
        groups = {}
        for name, keys in FORM_SECTIONS.items():
            fields = {field: value for field, value in schema.schema.items() if str(field) in keys}
            if name == "refresh" and inline is not None:
                options = inline.get("options", {})
                default = {
                    "general": normalized_schedule(options),
                    "overrides": dict(options.get(CONF_DATA_SCHEDULES) or {}),
                    CONF_STUDENT_SCHEDULES: dict(options.get(CONF_STUDENT_SCHEDULES) or {}),
                }
                fields = {
                    vol.Optional("schedule_editor", default=default): ScheduleEditorSelector(
                        {"entry_id": inline.get("entry_id", ""), "setup": setup}
                    )
                }
            if fields:
                expanded = setup and name == "account"
                expanded = expanded or bool(keys.intersection(errors or {}))
                defaults = {
                    str(field): field.default()
                    for field in fields
                    if isinstance(field, vol.Marker) and field.default is not vol.UNDEFINED
                }
                groups[vol.Optional(name, default=defaults)] = section(vol.Schema(fields), {"collapsed": not expanded})
        super().__init__(groups)

    def __call__(self, data):
        nested = dict(data)
        overrides = nested.pop(CONF_DATA_SCHEDULES, None)
        for name, keys in FORM_SECTIONS.items():
            values = {key: nested.pop(key) for key in keys if key in nested}
            if values:
                nested[name] = {**nested.get(name, {}), **values}
        validated = super().__call__(nested)
        flattened = {key: value for values in validated.values() for key, value in values.items()}
        if editor := flattened.pop("schedule_editor", None):
            flattened.update(editor["general"])
            flattened[CONF_DATA_SCHEDULES] = editor["overrides"]
            flattened[CONF_STUDENT_SCHEDULES] = editor[CONF_STUDENT_SCHEDULES]
        if overrides is not None:
            flattened[CONF_DATA_SCHEDULES] = DATA_SCHEDULES_SCHEMA(overrides)
        return flattened


def schedule_fields(options, *, inherit=False):
    """The same clock/day/interval controls in initial setup and the resource editor."""
    schedule = normalized_schedule(options)
    return {
        vol.Optional(
            CONF_SCHEDULE_TYPE, default=options.get(CONF_SCHEDULE_TYPE, schedule[CONF_SCHEDULE_TYPE])
        ): SelectSelector(
            SelectSelectorConfig(
                options=(["shared"] if inherit else []) + ["daily", "weekly", "interval"],
                translation_key="schedule_type",
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(CONF_SCHEDULE_TIME, default=options.get(CONF_SCHEDULE_TIME, schedule[CONF_SCHEDULE_TIME])): str,
        vol.Optional(CONF_SCHEDULE_DAYS, default=[str(day) for day in schedule[CONF_SCHEDULE_DAYS]]): SelectSelector(
            SelectSelectorConfig(
                options=[str(day) for day in range(7)],
                multiple=True,
                translation_key="schedule_days",
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Optional(CONF_SCHEDULE_INTERVAL, default=schedule[CONF_SCHEDULE_INTERVAL]): vol.All(
            int, vol.Range(min=5, max=1440)
        ),
    }


class DataScheduleFlow:
    """Drafts are committed only on Save; moving between resources does not persist changes."""

    def async_show_form(self, *, step_id, data_schema=None, errors=None, **kwargs):
        if step_id in {"user", "init"} and data_schema is not None:
            placeholders = dict(kwargs.get("description_placeholders") or {})
            entry = getattr(self, "_config_entry", None)
            placeholders["schedule_editor_url"] = "/mashov-schedules" + (
                f"?config_entry={entry.entry_id}" if entry else "?new=1"
            )
            kwargs["description_placeholders"] = placeholders
            inline = (
                {
                    "entry_id": entry.entry_id if entry else "",
                    "options": getattr(self, "_inline_schedule_options", dict(entry.options) if entry else {}),
                }
                if self.hass.data.get(DOMAIN, {}).get("inline_schedule_editor")
                else None
            )
            data_schema = GroupedSettingsSchema(data_schema, setup=step_id == "user", errors=errors, inline=inline)
            if errors:
                original_errors = errors
                errors = {
                    key: value
                    for key, value in errors.items()
                    if not any(key in keys for keys in FORM_SECTIONS.values())
                } | {
                    name: {key: value for key, value in original_errors.items() if key in keys}
                    for name, keys in FORM_SECTIONS.items()
                    if keys.intersection(original_errors)
                }
        return super().async_show_form(step_id=step_id, data_schema=data_schema, errors=errors, **kwargs)

    async def _schedule_labels(self):
        language = self.context.get("language")
        request = current_request.get()
        if language is None and request is not None and (user := request.get("hass_user")) is not None:
            from homeassistant.components.frontend.storage import async_user_store

            store = await async_user_store(self.hass, user.id)
            preference = store.data.get("language", {})
            if isinstance(preference, dict):
                language = preference.get("language")
        language = language or self.hass.config.language
        return await async_get_translations(self.hass, language, "selector", {DOMAIN})

    @staticmethod
    def _label(translations, selector, value):
        return translations.get(f"component.{DOMAIN}.selector.{selector}.options.{value}", str(value))

    def _schedule_description(self, translations, options, key):
        options = {**options, **(self.hass.data.get(DOMAIN, {}).get("yaml_options", {}) or {})}
        schedule = effective_schedule(options, key)
        kind = schedule[CONF_SCHEDULE_TYPE]
        text = self._label(translations, "schedule_type", kind)
        if kind == "interval":
            text += f" · {schedule[CONF_SCHEDULE_INTERVAL]} min"
        else:
            text += f" · {schedule[CONF_SCHEDULE_TIME]}"
            if kind == "weekly":
                text += " · " + ", ".join(
                    self._label(translations, "schedule_days", day) for day in schedule[CONF_SCHEDULE_DAYS]
                )
        scope = "custom" if key in (options.get(CONF_DATA_SCHEDULES) or {}) else "shared"
        text += " · " + self._label(translations, "schedule_scope", scope)
        if key not in enabled_data(options):
            text += " · " + self._label(translations, "schedule_scope", "disabled")
        return text

    async def _schedule_summary(self, options):
        labels = await self._schedule_labels()
        rows = [
            "| "
            + self._label(labels, "schedule_scope", "dataset")
            + " | "
            + self._label(labels, "schedule_scope", "schedule")
            + " |",
            "| --- | --- |",
        ]
        for key in DATA_KEYS:
            rows.append(
                f"| {self._label(labels, 'enabled_data', key)} | {self._schedule_description(labels, options, key)} |"
            )
        title = self._label(labels, "schedule_scope", "summary_title")
        help_title = self._label(labels, "schedule_scope", "help_title")
        help_text = self._label(labels, "schedule_scope", "help_text")
        return (
            f"<details>\n<summary>{title}</summary>\n\n" + "\n".join(rows) + "\n\n</details>\n\n"
            f"<details>\n<summary>ⓘ {help_title}</summary>\n\n{help_text}\n\n</details>"
        )

    async def async_step_data_schedules(self, user_input=None):
        if user_input is not None:
            key = user_input["dataset"]
            if key == "save":
                return await self._async_finish_schedules()
            if key in DATA_KEYS:
                self._schedule_key = key
                return await self.async_step_data_schedule()
        labels = await self._schedule_labels()
        choices = [{"value": "save", "label": self._label(labels, "schedule_scope", "save")}]
        choices += [
            {
                "value": key,
                "label": self._label(labels, "enabled_data", key)
                + " — "
                + self._schedule_description(labels, self._schedule_options, key),
            }
            for key in DATA_KEYS
        ]
        return self.async_show_form(
            step_id="data_schedules",
            data_schema=vol.Schema(
                {
                    vol.Required("dataset"): SelectSelector(
                        SelectSelectorConfig(options=choices, mode=SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
            description_placeholders={"schedule_summary": await self._schedule_summary(self._schedule_options)},
        )

    async def async_step_data_schedule(self, user_input=None):
        key = self._schedule_key
        current = effective_schedule(self._schedule_options, key)
        kind = current[CONF_SCHEDULE_TYPE] if key in self._schedule_options.get(CONF_DATA_SCHEDULES, {}) else "shared"
        if user_input is not None:
            kind = user_input[CONF_SCHEDULE_TYPE]
            if kind == "shared":
                overrides = dict(self._schedule_options.get(CONF_DATA_SCHEDULES) or {})
                overrides.pop(key, None)
                self._schedule_options[CONF_DATA_SCHEDULES] = overrides
                return await self.async_step_data_schedules()
            self._editing_schedule = {**current, CONF_SCHEDULE_TYPE: kind}
            return await self.async_step_data_schedule_settings()
        labels = await self._schedule_labels()
        return self.async_show_form(
            step_id="data_schedule",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCHEDULE_TYPE, default=kind): SelectSelector(
                        SelectSelectorConfig(
                            options=["shared", "daily", "weekly", "interval"],
                            translation_key="schedule_type",
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            description_placeholders={
                "dataset": self._label(labels, "enabled_data", key),
                "current_schedule": self._schedule_description(labels, self._schedule_options, key),
            },
        )

    async def async_step_data_schedule_settings(self, user_input=None):
        key = self._schedule_key
        options = self._editing_schedule
        errors = {}
        if user_input is not None:
            if user_input.get("schedule_action") == "back":
                return await self.async_step_data_schedule()
            changes = {k: v for k, v in user_input.items() if k != "schedule_action"}
            options = {**options, **changes}
            try:
                validated = SCHEDULE_SCHEMA(options)
            except vol.Invalid:
                errors["base"] = "invalid_data_schedule"
            else:
                overrides = dict(self._schedule_options.get(CONF_DATA_SCHEDULES) or {})
                overrides[key] = validated
                self._schedule_options[CONF_DATA_SCHEDULES] = overrides
                return await self.async_step_data_schedules()
        kind = options[CONF_SCHEDULE_TYPE]
        fields = schedule_fields(options)
        visible = {CONF_SCHEDULE_INTERVAL} if kind == "interval" else {CONF_SCHEDULE_TIME}
        if kind == "weekly":
            visible.add(CONF_SCHEDULE_DAYS)
        fields = {field: selector for field, selector in fields.items() if str(field) in visible}
        fields[vol.Optional("schedule_action", default="apply")] = SelectSelector(
            SelectSelectorConfig(
                options=["apply", "back"], translation_key="schedule_action", mode=SelectSelectorMode.DROPDOWN
            )
        )
        labels = await self._schedule_labels()
        return self.async_show_form(
            step_id="data_schedule_settings",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={
                "dataset": self._label(labels, "enabled_data", key),
                "schedule_kind": self._label(labels, "schedule_type", kind),
            },
        )
