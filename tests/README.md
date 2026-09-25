# Mashov Integration Tests

This directory contains all tests for the Mashov integration.

## Running Tests

### Run all tests:
```bash
pytest
```

### Run specific test file:
```bash
pytest tests/test_sensor.py
```

### Run with coverage:
```bash
pytest --cov=custom_components.mashov --cov-report=html
```

View coverage report: `open htmlcov/index.html`

### Run specific test:
```bash
pytest tests/test_sensor.py::test_homework_sensor -v
```

## Test Structure

```
tests/
├── __init__.py                 # Package marker
├── conftest.py                 # Shared fixtures
├── const.py                    # Test constants
├── test_init.py                # Integration setup/teardown tests
├── test_config_flow.py         # Config flow tests
├── test_sensor.py              # Sensor tests
├── fixtures/                   # Test data files
│   └── homework_data.json
└── README.md                   # This file
```

## Writing Tests

### Basic Test Example

```python
async def test_homework_sensor(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    """Test homework sensor."""
    mock_config_entry.add_to_hass(hass)
    
    with patch("custom_components.mashov.MashovClient") as mock_client:
        client = mock_client.return_value
        client.async_authenticate = AsyncMock(return_value=True)
        client.async_get_homework = AsyncMock(return_value=TEST_HOMEWORK)
        
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    
    state = hass.states.get("sensor.mashov_student_123_homework")
    assert state is not None
```

### Using Fixtures

Shared fixtures are defined in `conftest.py`:

```python
def test_something(hass, mock_config_entry, mock_mashov_client):
    # Use fixtures here
    pass
```

### Loading Test Data

```python
from pytest_homeassistant_custom_component.common import load_fixture


async def test_with_fixture_data(hass):
    data = load_fixture("homework_data.json")
    # Use data in test
```

## Test Coverage

Aim for:
- 80%+ overall coverage
- All critical paths tested
- Error handling tested
- Edge cases covered

Check coverage:
```bash
pytest --cov=custom_components.mashov --cov-report=term-missing
```

## Debugging Tests

### Run with verbose output:
```bash
pytest -v
```

### Run with print statements:
```bash
pytest -s
```

### Run last failed tests:
```bash
pytest --lf
```

### Debug with pdb:
```python
import pdb

pdb.set_trace()
```

## CI/CD

Tests run automatically on:
- Push to main branch
- Pull requests
- Release creation

See `.github/workflows/ci.yml` for configuration.

