import os
import sys
from unittest.mock import MagicMock

# The pytest-homeassistant-custom-component imports homeassistant.runner
# which requires Unix-only libraries. We mock them before pytest is started.
if os.name == "nt":
    sys.modules["fcntl"] = MagicMock()
    sys.modules["resource"] = MagicMock()

    import asyncio

    import pytest_socket

    def _loopback_only(*args, **kwargs):
        # Windows event-loop wakeups use TCP socket pairs. Keep external
        # connections blocked instead of disabling pytest-socket entirely.
        pytest_socket.socket_allow_hosts(["127.0.0.1", "::1"])

    pytest_socket.disable_socket = _loopback_only

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest

if __name__ == "__main__":
    sys.exit(pytest.main(sys.argv[1:]))
