"""Cross-platform pytest launcher for the Mashov test suite.

On Windows, pytest-homeassistant-custom-component cannot start as-is, so this
wrapper patches the environment before handing all CLI arguments to pytest.
"""

import os
import sys
from unittest.mock import MagicMock

# The pytest-homeassistant-custom-component imports homeassistant.runner
# which requires Unix-only libraries. We mock them before pytest is started.
if os.name == "nt":
    sys.modules["fcntl"] = MagicMock()
    sys.modules["resource"] = MagicMock()

    # Imported only after the stubs above so nothing sees the real (missing) modules.

    import asyncio

    import pytest_socket

    def _loopback_only(*args, **kwargs):
        """Replacement for ``pytest_socket.disable_socket`` that allows loopback only."""
        # Windows event-loop wakeups use TCP socket pairs. Keep external
        # connections blocked instead of disabling pytest-socket entirely.
        pytest_socket.socket_allow_hosts(["127.0.0.1", "::1"])

    # pytest-homeassistant-custom-component calls disable_socket() for every
    # test; replace it so loopback stays reachable while the internet is blocked.
    pytest_socket.disable_socket = _loopback_only

    # The default Proactor loop is incompatible with some HA test fixtures;
    # the selector loop matches the Unix behaviour the plugin expects.

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest

# Forward all command-line arguments to pytest unchanged.
if __name__ == "__main__":
    sys.exit(pytest.main(sys.argv[1:]))
