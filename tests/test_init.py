"""Tests for integration setup, services and option validation."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from ariston.ariston_api import ConnectionException
from ariston.const import DeviceAttribute, SystemType
from homeassistant.const import (
    CONF_DEVICE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.util.unit_system import METRIC_SYSTEM

from custom_components.ariston import (
    ATTR_DEVICE_ID,
    ATTR_END_DATE,
    ATTR_ITEM_ID,
    ATTR_VALUE,
    ATTR_ZONE,
    COORDINATOR,
    PLATFORMS,
    SERVICE_CREATE_VACATION,
    SERVICE_SET_ITEM_BY_ID,
    SET_ITEM_BY_ID_SCHEMA,
    _async_register_galevo_services,
    _async_remove_galevo_services,
    _entry_has_galevo_device,
    _get_option_interval,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.ariston.const import (
    BUS_ERRORS_COORDINATOR,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    ENERGY_COORDINATOR,
    MIN_SCAN_INTERVAL_SECONDS,
)


@pytest.fixture
def hass():
    """Create a minimal Home Assistant instance."""
    hass = MagicMock()
    hass.config.units = METRIC_SYSTEM
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    return hass


@pytest.fixture
def entry():
    """Create a config entry for a device without metering."""
    entry = MagicMock()
    entry.entry_id = "entry-id"
    entry.data = {
        CONF_USERNAME: "user@example.com",
        CONF_PASSWORD: "secret",
        CONF_DEVICE: {
            DeviceAttribute.NAME: "Boiler",
            DeviceAttribute.GW: "gateway",
        },
    }
    entry.options = {}
    entry.runtime_data = None
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    return entry


@pytest.fixture
def device():
    """Create a VELIS device without metering."""
    device = MagicMock()
    device.name = "Boiler"
    device.system_type = SystemType.VELIS
    device.has_metering = False
    device.features = {"feature": True}
    device.async_get_features = AsyncMock()
    device.async_update_state = AsyncMock()
    device.async_get_bus_errors = AsyncMock()
    device.async_update_energy = AsyncMock()
    return device


def _coordinator_factory():
    def _make_coordinator(*args, **kwargs):
        coordinator = MagicMock()
        coordinator.async_config_entry_first_refresh = AsyncMock()
        coordinator.async_refresh = AsyncMock()
        return coordinator

    return _make_coordinator


async def test_setup_without_metering_skips_energy_coordinator(hass, entry, device):
    """A device without metering must not expose the energy coordinator."""
    ariston = MagicMock()
    ariston.async_connect = AsyncMock(return_value=True)
    ariston.async_hello = AsyncMock(return_value=device)

    with (
        patch("custom_components.ariston.Ariston", return_value=ariston),
        patch(
            "custom_components.ariston.DeviceDataUpdateCoordinator",
            side_effect=_coordinator_factory(),
        ),
    ):
        assert await async_setup_entry(hass, entry)

    assert set(entry.runtime_data) == {COORDINATOR, BUS_ERRORS_COORDINATOR}
    assert ENERGY_COORDINATOR not in entry.runtime_data
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, PLATFORMS
    )


async def test_setup_invalid_credentials_raise_auth_failed(hass, entry):
    """Invalid credentials must start the reauth flow."""
    ariston = MagicMock()
    ariston.async_connect = AsyncMock(return_value=False)

    with (
        patch("custom_components.ariston.Ariston", return_value=ariston),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await async_setup_entry(hass, entry)


async def test_setup_connection_error_is_retried(hass, entry):
    """Connection errors are retryable and reported as ConfigEntryNotReady."""
    ariston = MagicMock()
    ariston.async_connect = AsyncMock(
        side_effect=ConnectionException("Connection failed")
    )

    with (
        patch("custom_components.ariston.Ariston", return_value=ariston),
        pytest.raises(ConfigEntryNotReady),
    ):
        await async_setup_entry(hass, entry)


@pytest.mark.parametrize(
    "error",
    [ConnectionException(401), ConnectionException("Login failed")],
)
async def test_setup_auth_connection_error_starts_reauth(hass, entry, error):
    """Connection errors that mean bad credentials must start reauth."""
    ariston = MagicMock()
    ariston.async_connect = AsyncMock(side_effect=error)

    with (
        patch("custom_components.ariston.Ariston", return_value=ariston),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await async_setup_entry(hass, entry)


async def test_setup_missing_device_is_retried(hass, entry):
    """A missing gateway is retryable and reported as ConfigEntryNotReady."""
    ariston = MagicMock()
    ariston.async_connect = AsyncMock(return_value=True)
    ariston.async_hello = AsyncMock(return_value=None)

    with (
        patch("custom_components.ariston.Ariston", return_value=ariston),
        pytest.raises(ConfigEntryNotReady),
    ):
        await async_setup_entry(hass, entry)


async def test_setup_unexpected_error_is_not_wrapped(hass, entry, device):
    """Unexpected programming errors must surface unchanged."""
    device.features = None
    device.async_get_features = AsyncMock(side_effect=RuntimeError("boom"))
    ariston = MagicMock()
    ariston.async_connect = AsyncMock(return_value=True)
    ariston.async_hello = AsyncMock(return_value=device)

    with (
        patch("custom_components.ariston.Ariston", return_value=ariston),
        patch(
            "custom_components.ariston.DeviceDataUpdateCoordinator",
            side_effect=_coordinator_factory(),
        ),
        pytest.raises(RuntimeError, match="boom"),
    ):
        await async_setup_entry(hass, entry)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, DEFAULT_SCAN_INTERVAL_SECONDS),
        (120, 120),
        ("120", 120),
        (MIN_SCAN_INTERVAL_SECONDS - 1, DEFAULT_SCAN_INTERVAL_SECONDS),
        ("invalid", DEFAULT_SCAN_INTERVAL_SECONDS),
    ],
)
def test_get_option_interval_validates_values(value, expected):
    """Option intervals fall back safely when invalid or too small."""
    entry = MagicMock()
    entry.options = {} if value is None else {CONF_SCAN_INTERVAL: value}

    assert (
        _get_option_interval(
            entry,
            CONF_SCAN_INTERVAL,
            DEFAULT_SCAN_INTERVAL_SECONDS,
            MIN_SCAN_INTERVAL_SECONDS,
        )
        == expected
    )


def test_galevo_services_are_registered_once():
    """Registering services for several entries must not duplicate them."""
    hass = MagicMock()
    services: set[tuple[str, str]] = set()

    def has_service(domain, service):
        return (domain, service) in services

    def register(domain, service, handler, schema=None):
        services.add((domain, service))

    hass.services.has_service.side_effect = has_service
    hass.services.async_register.side_effect = register

    _async_register_galevo_services(hass)
    _async_register_galevo_services(hass)

    assert services == {
        (DOMAIN, SERVICE_CREATE_VACATION),
        (DOMAIN, SERVICE_SET_ITEM_BY_ID),
    }
    assert hass.services.async_register.call_count == 2


def test_galevo_services_are_removed():
    """All GALEVO services are removed when the last entry unloads."""
    hass = MagicMock()
    hass.services.has_service.return_value = True

    _async_remove_galevo_services(hass)

    assert [call.args for call in hass.services.async_remove.call_args_list] == [
        (DOMAIN, SERVICE_CREATE_VACATION),
        (DOMAIN, SERVICE_SET_ITEM_BY_ID),
    ]


def test_entry_has_galevo_device():
    """Only loaded GALEVO entries keep the services alive."""
    entry = MagicMock()
    entry.runtime_data = {COORDINATOR: MagicMock()}
    entry.runtime_data[COORDINATOR].device.system_type = SystemType.GALEVO
    assert _entry_has_galevo_device(entry)

    entry.runtime_data[COORDINATOR].device.system_type = SystemType.VELIS
    assert not _entry_has_galevo_device(entry)

    entry.runtime_data = {}
    assert not _entry_has_galevo_device(entry)


@pytest.mark.parametrize(
    ("remaining_system", "removed"), [(None, True), (SystemType.GALEVO, False)]
)
async def test_unload_removes_services_only_without_other_galevo_entry(
    hass, entry, remaining_system, removed
):
    """Services disappear with the last loaded GALEVO entry."""
    entry.runtime_data = {COORDINATOR: MagicMock()}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    remaining_entry = MagicMock()
    remaining_entry.entry_id = "other-entry"
    remaining_entry.runtime_data = None
    if remaining_system is not None:
        remaining_entry.runtime_data = {COORDINATOR: MagicMock()}
        remaining_entry.runtime_data[COORDINATOR].device.system_type = remaining_system
    hass.config_entries.async_entries.return_value = [entry, remaining_entry]

    with patch(
        "custom_components.ariston._async_remove_galevo_services"
    ) as remove_services:
        assert await async_unload_entry(hass, entry)

    assert remove_services.called is removed
    assert entry.runtime_data is None


async def test_create_vacation_service_refreshes_target_device(hass, entry):
    """The create_vacation service resolves and refreshes its target device."""
    registered = {}

    def register(domain, service, handler, schema=None):
        registered[service] = handler

    hass.services.has_service.return_value = False
    hass.services.async_register.side_effect = register
    _async_register_galevo_services(hass)

    target_device = MagicMock()
    target_device.system_type = SystemType.GALEVO
    target_device.async_set_holiday = AsyncMock()
    coordinator = MagicMock()
    coordinator.device = target_device
    coordinator.async_request_refresh = AsyncMock()
    target_entry = MagicMock()
    target_entry.runtime_data = {COORDINATOR: coordinator}
    hass.config_entries.async_get_entry.return_value = target_entry

    device_entry = MagicMock()
    device_entry.config_entries = {"target-entry"}
    registry = MagicMock()
    registry.async_get.return_value = device_entry

    holiday_end = date(2026, 12, 1)
    with patch("custom_components.ariston.dr.async_get", return_value=registry):
        await registered[SERVICE_CREATE_VACATION](
            SimpleNamespace(
                data={
                    ATTR_DEVICE_ID: "device-id",
                    ATTR_END_DATE: holiday_end,
                }
            )
        )

    target_device.async_set_holiday.assert_awaited_once_with(holiday_end)
    coordinator.async_request_refresh.assert_awaited_once()


def test_set_item_schema_requires_a_real_zone():
    """The set_item_by_id service rejects zone 0."""
    with pytest.raises(vol.Invalid):
        SET_ITEM_BY_ID_SCHEMA(
            {
                ATTR_DEVICE_ID: "device-id",
                ATTR_ITEM_ID: "item",
                ATTR_ZONE: 0,
                ATTR_VALUE: 42.5,
            }
        )


async def test_set_item_service_refreshes_target_device(hass, entry):
    """The set_item_by_id service resolves and refreshes its target device."""
    registered = {}

    def register(domain, service, handler, schema=None):
        registered[service] = handler

    hass.services.has_service.return_value = False
    hass.services.async_register.side_effect = register
    _async_register_galevo_services(hass)

    target_device = MagicMock()
    target_device.system_type = SystemType.GALEVO
    target_device.async_set_item_by_id = AsyncMock()
    coordinator = MagicMock()
    coordinator.device = target_device
    coordinator.async_request_refresh = AsyncMock()
    target_entry = MagicMock()
    target_entry.runtime_data = {COORDINATOR: coordinator}
    hass.config_entries.async_get_entry.return_value = target_entry

    device_entry = MagicMock()
    device_entry.config_entries = {"target-entry"}
    registry = MagicMock()
    registry.async_get.return_value = device_entry

    with patch("custom_components.ariston.dr.async_get", return_value=registry):
        await registered[SERVICE_SET_ITEM_BY_ID](
            SimpleNamespace(
                data={
                    ATTR_DEVICE_ID: "device-id",
                    ATTR_ITEM_ID: "item",
                    ATTR_ZONE: 1,
                    ATTR_VALUE: 42.5,
                }
            )
        )

    target_device.async_set_item_by_id.assert_awaited_once_with("item", 42.5, 1)
    coordinator.async_request_refresh.assert_awaited_once()
