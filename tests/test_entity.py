"""Tests for entity identities, device info and registry migrations."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from ariston.const import DeviceProperties, SystemType, WheType

from custom_components.ariston import _async_migrate_device_identifier
from custom_components.ariston.climate import AristonThermostat
from custom_components.ariston.const import (
    ARISTON_CLIMATE_TYPES,
    ARISTON_NUMBER_TYPES,
    ARISTON_SENSOR_TYPES,
)
from custom_components.ariston.entity import (
    AristonEntity,
    async_migrate_entity_unique_ids,
)


def _device(serial_number="SN123"):
    device = MagicMock()
    device.gateway = "gw"
    device.serial_number = serial_number
    device.name = "Boiler"
    device.firmware_version = "1.0"
    device.system_type = SystemType.VELIS
    device.whe_type = WheType.Lux
    device.whe_model_type = 0
    device.zone_numbers = [1]
    return device


def _coordinator(device):
    coordinator = MagicMock()
    coordinator.device = device
    return coordinator


def _registry_entry(unique_id):
    return SimpleNamespace(
        unique_id=unique_id,
        entity_id="sensor.old",
        domain="sensor",
        platform="ariston",
    )


def test_base_entity_unique_id_uses_description_key():
    """Entity unique IDs no longer depend on the display name."""
    device = _device()
    coordinator = _coordinator(device)
    description = next(
        description
        for description in ARISTON_SENSOR_TYPES
        if description.key == DeviceProperties.CH_FLOW_TEMP
    )

    entity = AristonEntity(coordinator, description)
    assert entity.unique_id == f"gw-{DeviceProperties.CH_FLOW_TEMP}"

    zoned_description = next(
        description for description in ARISTON_NUMBER_TYPES if description.zone
    )
    zoned_entity = AristonEntity(coordinator, zoned_description, zone=1)
    assert zoned_entity.unique_id == f"gw-{zoned_description.key}-1"


def test_device_info_uses_gateway_and_serial():
    """The gateway identifier is always present; empty serials are not."""
    device = _device()
    coordinator = _coordinator(device)
    description = ARISTON_SENSOR_TYPES[0]

    entity = AristonEntity(coordinator, description)
    assert entity.device_info["identifiers"] == {
        ("ariston", "gw"),
        ("ariston", "SN123"),
    }

    device.serial_number = None
    assert AristonEntity(coordinator, description).device_info["identifiers"] == {
        ("ariston", "gw")
    }


async def test_migrate_entity_unique_ids(monkeypatch):
    """Legacy name-based IDs are mapped to the new stable IDs."""
    device = _device()
    entry = MagicMock()
    entry.entry_id = "entry-id"

    captured = {}

    async def fake_migrate(hass, entry_id, callback):
        captured["callback"] = callback

    monkeypatch.setattr(
        "custom_components.ariston.entity.er.async_migrate_entries",
        fake_migrate,
    )
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None
    monkeypatch.setattr(
        "custom_components.ariston.entity.er.async_get", lambda hass: registry
    )

    await async_migrate_entity_unique_ids(MagicMock(), entry, device)
    callback = captured["callback"]

    sensor_description = next(
        description
        for description in ARISTON_SENSOR_TYPES
        if description.key == DeviceProperties.CH_FLOW_TEMP
    )
    assert callback(_registry_entry(f"gw-{sensor_description.name}")) == {
        "new_unique_id": f"gw-{sensor_description.key}"
    }

    number_description = next(
        description for description in ARISTON_NUMBER_TYPES if description.zone
    )
    assert callback(_registry_entry(f"gw-{number_description.name} 1-1")) == {
        "new_unique_id": f"gw-{number_description.key}-1"
    }

    climate_description = ARISTON_CLIMATE_TYPES[0]
    assert callback(_registry_entry("gw_1")) == {
        "new_unique_id": f"gw-{climate_description.key}-1"
    }
    assert callback(_registry_entry("already-migrated")) is None


async def test_migrate_entity_unique_ids_skips_collision(monkeypatch):
    """A migration must not overwrite an existing stable unique ID."""
    device = _device()
    entry = MagicMock()
    entry.entry_id = "entry-id"

    captured = {}

    async def fake_migrate(hass, entry_id, callback):
        captured["callback"] = callback

    registry = MagicMock()
    registry.async_get_entity_id.return_value = "sensor.existing"
    monkeypatch.setattr(
        "custom_components.ariston.entity.er.async_migrate_entries",
        fake_migrate,
    )
    monkeypatch.setattr(
        "custom_components.ariston.entity.er.async_get", lambda hass: registry
    )

    await async_migrate_entity_unique_ids(MagicMock(), entry, device)
    sensor_description = next(
        description
        for description in ARISTON_SENSOR_TYPES
        if description.key == DeviceProperties.CH_FLOW_TEMP
    )

    assert (
        captured["callback"](
            SimpleNamespace(
                unique_id=f"gw-{sensor_description.name}",
                entity_id="sensor.old",
                domain="sensor",
                platform="ariston",
            )
        )
        is None
    )


async def test_migrate_entity_unique_ids_ignores_missing_gateway(monkeypatch):
    """A device without a gateway cannot migrate registry entries safely."""
    device = _device()
    device.gateway = None
    entry = MagicMock()
    entry.entry_id = "entry-id"

    async def fake_migrate(hass, entry_id, callback):
        raise AssertionError("migration must not run")

    monkeypatch.setattr(
        "custom_components.ariston.entity.er.async_migrate_entries",
        fake_migrate,
    )

    await async_migrate_entity_unique_ids(MagicMock(), entry, device)


async def test_migrate_entity_unique_ids_without_zones(monkeypatch):
    """VELIS devices have no zone_numbers attribute and must still migrate."""
    device = SimpleNamespace(gateway="gw")
    entry = MagicMock()
    entry.entry_id = "entry-id"

    async def fake_migrate(hass, entry_id, callback):
        assert callback(SimpleNamespace(unique_id="gw_1")) is None

    monkeypatch.setattr(
        "custom_components.ariston.entity.er.async_migrate_entries",
        fake_migrate,
    )

    await async_migrate_entity_unique_ids(MagicMock(), entry, device)


def test_migrate_device_identifier_without_serial(monkeypatch):
    """A legacy shared empty identifier is replaced by the gateway."""
    device = _device(serial_number=None)
    legacy_device = MagicMock()
    legacy_device.id = "device-id"
    legacy_device.identifiers = {("ariston", "")}
    registry = MagicMock()
    registry.async_get_device.side_effect = [None, legacy_device]
    monkeypatch.setattr("custom_components.ariston.dr.async_get", lambda hass: registry)

    _async_migrate_device_identifier(MagicMock(), device)

    registry.async_update_device.assert_called_once_with(
        "device-id",
        new_identifiers={("ariston", "gw")},
    )


def test_migrate_device_identifier_keeps_serial(monkeypatch):
    """Existing serial identifiers are preserved while adding the gateway."""
    device = _device()
    legacy_device = MagicMock()
    legacy_device.id = "device-id"
    legacy_device.identifiers = {("ariston", "SN123")}
    registry = MagicMock()
    registry.async_get_device.side_effect = [None, legacy_device]
    monkeypatch.setattr("custom_components.ariston.dr.async_get", lambda hass: registry)

    _async_migrate_device_identifier(MagicMock(), device)

    registry.async_update_device.assert_called_once_with(
        "device-id",
        new_identifiers={("ariston", "SN123"), ("ariston", "gw")},
    )


def test_migrate_device_identifier_is_idempotent(monkeypatch):
    """A device already registered by gateway is left untouched."""
    device = _device()
    registry = MagicMock()
    registry.async_get_device.return_value = MagicMock()
    monkeypatch.setattr("custom_components.ariston.dr.async_get", lambda hass: registry)

    _async_migrate_device_identifier(MagicMock(), device)

    registry.async_update_device.assert_not_called()


def test_climate_names_include_zone_only_when_needed():
    """Multi-zone climates get distinct names; single-zone names stay unchanged."""
    device = _device()
    device.zone_numbers = [1, 2]
    coordinator = _coordinator(device)
    description = ARISTON_CLIMATE_TYPES[0]

    thermostat = AristonThermostat(1, coordinator, description)
    assert thermostat.name == "Boiler Zone 1"
    assert thermostat.unique_id == f"gw-{description.key}-1"

    device.zone_numbers = [1]
    assert thermostat.name == "Boiler"
