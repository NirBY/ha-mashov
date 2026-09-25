# Contributing to Mashov Integration

Thank you for your interest in contributing to the Mashov integration for Home Assistant! 🎉

## Getting Started

### Prerequisites

- Python 3.11 or higher
- Home Assistant 2025.1.0 or higher
- Git
- Visual Studio Code (recommended)

### Development Setup

1. **Fork and clone the repository**:
   ```bash
   git clone https://github.com/NirBY/ha-mashov.git
   cd ha-mashov
   ```

2. **Install development dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Install pre-commit hooks** (optional but recommended):
   ```bash
   pre-commit install
   ```

### Using VS Code Dev Container

The easiest way to get started is using VS Code with Dev Containers:

1. Install [VS Code](https://code.visualstudio.com/) and the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
2. Open the repository in VS Code
3. Click "Reopen in Container" when prompted
4. All dependencies will be installed automatically

## Making Changes

### Code Style

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Check for issues
ruff check .

# Format code
ruff format .
```

### Testing

All changes should include tests. We use [pytest](https://docs.pytest.org/) with [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component):

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_sensor.py

# Run with coverage
pytest --cov=custom_components.mashov --cov-report=html
```

### Writing Tests

Place tests in the `tests/` directory:

```python
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.mashov.const import DOMAIN


async def test_sensor_setup(hass):
    """Test sensor setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "test", "password": "test"},
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.mashov_test_homework") is not None
```

## Commit Guidelines

We follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `test:` Adding or updating tests
- `refactor:` Code refactoring
- `chore:` Maintenance tasks

Examples:
```bash
git commit -m "feat: add support for multiple schools"
git commit -m "fix: resolve authentication timeout issue"
git commit -m "docs: update README with new examples"
```

## Submitting Changes

1. **Create a new branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes and commit**:
   ```bash
   git add .
   git commit -m "feat: your feature description"
   ```

3. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

4. **Create a Pull Request**:
   - Go to the [repository](https://github.com/NirBY/ha-mashov)
   - Click "New Pull Request"
   - Select your branch
   - Fill in the PR template
   - Submit!

## Blueprint Contributions

When modifying blueprints:

1. Update the version number in the blueprint file
2. Update `CHANGELOG.md` with changes
3. Test thoroughly with real Home Assistant instance
4. Include example configuration in PR description

## Reporting Issues

When reporting issues, please include:

- Home Assistant version
- Integration version
- Relevant logs (from Settings → System → Logs)
- Steps to reproduce
- Expected vs actual behavior

## Questions?

- Open a [Discussion](https://github.com/NirBY/ha-mashov/discussions) for questions
- Open an [Issue](https://github.com/NirBY/ha-mashov/issues) for bugs
- Check existing issues before creating new ones

## Code of Conduct

Be respectful, inclusive, and constructive in all interactions.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing! 🙏

