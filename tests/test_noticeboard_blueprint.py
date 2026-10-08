"""The noticeboard blueprint runs in Home Assistant's real automation engine.

Protects: only notices with a new ``eventid`` are announced (a replacement counts, a
removal does not); startup/recovery states are a baseline, never news; HTML is removed;
speech never happens during the internal 22:00-07:00 quiet hours, while notifications
are still sent; and the speaker volume is restored after speaking.
"""

import asyncio
from pathlib import Path
import shutil

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

BLUEPRINT = Path(__file__).parent.parent / "blueprints/automation/mashov/mashov_noticeboard_announce.yaml"
SENSOR = "sensor.kid_noticeboard"
SPEAKER = "media_player.kitchen"


def _notice(eventid: str, text: str) -> dict:
    """A noticeboard item shaped like the Mashov API (ID plus HTML text)."""
    return {"eventid": eventid, "eventtext": text, "expirationDate": "2039-09-04T00:00:00"}


def _set_board(hass: HomeAssistant, items: list[dict], state: str | None = None, status: str = "ok") -> None:
    hass.states.async_set(
        SENSOR,
        state if state is not None else str(len(items)),
        {"items": items, "source_status": status, "student_name": "נועה"},
    )


@pytest.fixture
async def calls(hass: HomeAssistant, tmp_path):
    """Load the blueprint as an automation, with recording fakes for every action it calls."""
    hass.config.config_dir = str(tmp_path)
    await hass.config.async_set_time_zone("Asia/Jerusalem")
    target = tmp_path / "blueprints/automation/mashov"
    target.mkdir(parents=True)
    shutil.copy(BLUEPRINT, target / BLUEPRINT.name)

    recorded: dict[str, list[dict]] = {}

    def record(name):
        async def handler(call: ServiceCall):
            recorded.setdefault(name, []).append(dict(call.data))
            if name == "media_player.volume_set":
                hass.states.async_set(SPEAKER, "idle", {"volume_level": call.data["volume_level"]})
            if name == "tts.speak":
                # The speaker plays, then goes idle a few loop iterations later, after the
                # automation has seen "playing". (The clock is frozen, so waits never time out.)
                volume = hass.states.get(SPEAKER).attributes.get("volume_level")
                hass.states.async_set(SPEAKER, "playing", {"volume_level": volume})

                async def finish():
                    for _ in range(5):
                        await asyncio.sleep(0)
                    hass.states.async_set(SPEAKER, "idle", {"volume_level": volume})

                hass.async_create_task(finish())

        return handler

    for name in (
        "logbook.log",
        "persistent_notification.create",
        "notify.mobile_app_phone",
        "media_player.turn_on",
        "media_player.volume_set",
        "tts.speak",
    ):
        domain, service = name.split(".")
        hass.services.async_register(domain, service, record(name))

    hass.states.async_set(SPEAKER, "idle", {"volume_level": 0.2})
    _set_board(hass, [_notice("61", "<p>Existing notice</p>")])  # baseline before the automation exists
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": f"mashov/{BLUEPRINT.name}",
                    "input": {
                        "noticeboard_sensors": [SENSOR],
                        "notify_service": "notify.mobile_app_phone",
                        "media_player": SPEAKER,
                        "tts_engine": "tts.google",
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()
    return recorded


async def test_new_notice_is_notified_and_read_aloud_in_the_daytime(hass, calls, freezer):
    """A new eventid sends both notifications, speaks plain text, and restores the volume."""
    freezer.move_to("2026-10-06 07:30:00+00:00")  # 10:30 in Israel
    _set_board(
        hass,
        [_notice("61", "<p>Existing notice</p>"), _notice("70", "<p>Trip on <b>Sunday</b>&nbsp;at 8</p>")],
    )
    await hass.async_block_till_done()

    assert calls["persistent_notification.create"][0]["message"] == "Trip on Sunday at 8"
    assert "נועה" in calls["persistent_notification.create"][0]["title"]
    assert calls["notify.mobile_app_phone"][0]["message"] == "Trip on Sunday at 8"
    assert "Trip on Sunday at 8" in calls["tts.speak"][0]["message"]
    assert "Existing notice" not in calls["tts.speak"][0]["message"]
    assert [c["volume_level"] for c in calls["media_player.volume_set"]] == [0.7, 0.2]


async def test_quiet_hours_skip_speech_but_still_notify(hass, calls, freezer):
    """At 23:30 local time the notice is notified, but nothing is spoken or turned up."""
    freezer.move_to("2026-10-06 20:30:00+00:00")  # 23:30 in Israel
    _set_board(hass, [_notice("61", "<p>Existing notice</p>"), _notice("71", "Night notice")])
    await hass.async_block_till_done()

    assert calls["notify.mobile_app_phone"][0]["message"] == "Night notice"
    assert "tts.speak" not in calls
    assert "media_player.volume_set" not in calls
    assert any("quiet hours" in c["message"] for c in calls["logbook.log"])


async def test_replacement_counts_as_new_but_removal_does_not(hass, calls, freezer):
    """Same count with a different notice is news; removing a notice is not."""
    freezer.move_to("2026-10-06 07:30:00+00:00")
    _set_board(hass, [_notice("72", "Replacement")])  # 61 removed, 72 added: still one notice
    await hass.async_block_till_done()
    assert [c["message"] for c in calls["notify.mobile_app_phone"]] == ["Replacement"]

    _set_board(hass, [])
    await hass.async_block_till_done()
    assert len(calls["notify.mobile_app_phone"]) == 1


async def test_recovery_from_unavailable_is_a_baseline(hass, calls, freezer):
    """Coming back from unavailable (restart, outage) never re-announces existing notices."""
    freezer.move_to("2026-10-06 07:30:00+00:00")
    _set_board(hass, [], state="unavailable")
    await hass.async_block_till_done()
    _set_board(hass, [_notice("61", "Existing notice"), _notice("73", "Already there")])
    await hass.async_block_till_done()

    assert "notify.mobile_app_phone" not in calls
    assert "tts.speak" not in calls


async def test_failed_tts_restores_volume(hass, calls, freezer):
    """A TTS service failure must not leave the speaker turned up."""
    freezer.move_to("2026-10-06 07:30:00+00:00")
    attempted = asyncio.Event()

    async def failed_tts(call):
        attempted.set()
        raise HomeAssistantError("Synthetic TTS failure")

    hass.services.async_register("tts", "speak", failed_tts)
    _set_board(hass, [_notice("74", "Notice with unavailable TTS")])
    await attempted.wait()
    # Let the script enter its playback-start timeout before advancing the frozen clock.
    for _ in range(10):
        await asyncio.sleep(0)
    freezer.tick(121)
    async_fire_time_changed(hass, dt_util.utcnow(), fire_all=True)
    await hass.async_block_till_done()

    assert [c["volume_level"] for c in calls["media_player.volume_set"]] == [0.7, 0.2]
    assert calls["notify.mobile_app_phone"][0]["message"] == "Notice with unavailable TTS"


async def test_quiet_hours_begin_while_preparing_speaker(hass, calls, freezer):
    """Starting before 22:00 is not permission to start TTS after 22:00."""
    freezer.move_to("2026-10-06 18:59:59+00:00")  # 21:59:59 in Israel

    async def turn_on(call):
        freezer.move_to("2026-10-06 19:00:01+00:00")

    hass.services.async_register("media_player", "turn_on", turn_on)
    _set_board(hass, [_notice("75", "Late notice")])
    await hass.async_block_till_done()

    assert "tts.speak" not in calls
    assert [c["volume_level"] for c in calls["media_player.volume_set"]] == [0.7, 0.2]
    assert any("quiet hours began" in c["message"] for c in calls["logbook.log"])


async def test_slow_speaker_keeps_volume_until_playback_finishes(hass, calls, freezer):
    """A Cast-like delayed start must not restore volume at the old ten-second deadline."""
    freezer.move_to("2026-10-06 07:30:00+00:00")
    attempted = asyncio.Event()

    async def delayed_tts(call):
        attempted.set()

    hass.services.async_register("tts", "speak", delayed_tts)
    _set_board(hass, [_notice("76", "Slow speaker notice")])
    await attempted.wait()
    for _ in range(10):
        await asyncio.sleep(0)
    freezer.tick(15)
    async_fire_time_changed(hass, dt_util.utcnow())
    for _ in range(20):
        await asyncio.sleep(0)
    assert [c["volume_level"] for c in calls["media_player.volume_set"]] == [0.7]

    hass.states.async_set(SPEAKER, "playing", {"volume_level": 0.7})
    for _ in range(20):
        await asyncio.sleep(0)
    assert [c["volume_level"] for c in calls["media_player.volume_set"]] == [0.7]
    hass.states.async_set(SPEAKER, "idle", {"volume_level": 0.7})
    await hass.async_block_till_done()
    assert [c["volume_level"] for c in calls["media_player.volume_set"]] == [0.7, 0.2]
