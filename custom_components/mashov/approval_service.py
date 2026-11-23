"""Admin service answer_school_activity: the integration's only write to Mashov.

It runs only with the hub option allow_approval_answers on. The client re-reads the
activity from Mashov right before the PUT, so refusals use current data, not the
last refresh.
"""

from __future__ import annotations

import logging

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError  # type: ignore
from homeassistant.helpers import config_validation as cv  # type: ignore
import voluptuous as vol  # type: ignore

from .approvals import ANSWER_CODES, PARENT_APPROVALS
from .const import DOMAIN
from .data_selection import approval_answers_enabled
from .mashov_client import MashovAnswerRefusedError, MashovError

_LOGGER = logging.getLogger(__name__)

SERVICE_ANSWER_SCHOOL_ACTIVITY = "answer_school_activity"
REMARK_MAX_LENGTH = 500


def _activity_id(value):
    """Whole numbers only: a truncated float or a boolean would answer another activity."""
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise vol.Invalid("activity_id must be a whole number")
    return value


ANSWER_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
        vol.Required("activity_id"): vol.All(_activity_id, vol.Coerce(int), vol.Range(min=1)),
        vol.Required("student"): cv.string,
        vol.Required("answer"): vol.In(list(ANSWER_CODES)),
        vol.Optional("remark", default=""): vol.All(cv.string, vol.Length(max=REMARK_MAX_LENGTH)),
    }
)
REFUSALS = {
    "unknown_activity": "Mashov does not list this activity for this account",
    "deadline_unknown": "Mashov did not return an answer deadline for this activity; answer it in the Mashov portal",
    "deadline_passed": "The answer deadline for this activity has passed",
    "has_questions": "This activity has questions; answer it in the Mashov portal",
    "student_not_covered": "This activity does not apply to the selected student",
}


def _hub(hass, entry_id):
    """A write targets exactly one loaded hub; without entry_id there must be only one."""
    hubs = {
        key: hub for key, hub in hass.data.get(DOMAIN, {}).items() if isinstance(hub, dict) and "coordinator" in hub
    }
    if entry_id:
        if entry_id not in hubs:
            raise ServiceValidationError(f"Mashov hub {entry_id} is not loaded")
        return hubs[entry_id]
    if len(hubs) != 1:
        raise ServiceValidationError("Specify entry_id: zero or several Mashov hubs are loaded")
    return next(iter(hubs.values()))


def _student_id(data, student):
    """Accept the student id or slug shown on the sensor."""
    for candidate in (data or {}).get("students", []):
        if student in (str(candidate.get("id")), candidate.get("slug")):
            return candidate["id"]
    raise ServiceValidationError("Unknown student for this hub")


async def async_handle_answer(hass, call):
    """Send one parent answer, then refresh the approvals sensors."""
    hub = _hub(hass, call.data.get("entry_id"))
    coordinator = hub["coordinator"]
    if not approval_answers_enabled(coordinator.entry.options):
        raise ServiceValidationError("Turn on 'Allow answering parent approvals' in the hub options first")
    student_id = _student_id(coordinator.data, call.data["student"])
    try:
        await hub["client"].async_answer_school_activity(
            call.data["activity_id"], student_id, call.data["answer"], call.data["remark"]
        )
    except MashovAnswerRefusedError as err:
        raise ServiceValidationError(REFUSALS[err.reason]) from err
    except MashovError as err:
        raise HomeAssistantError(str(err)) from err
    try:
        await coordinator.async_refresh_datasets({PARENT_APPROVALS})
    except Exception:  # noqa: BLE001 - the answer was sent; a failed refresh must not look like a failed answer
        _LOGGER.warning("School activity answered; refreshing parent approvals failed", exc_info=True)
