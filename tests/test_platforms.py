"""Tests for the entity platforms (sensors, switches, binary sensors)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from ariston.const import (
    CustomDeviceFeatures,
    EvoDeviceProperties,
    EvoLydosDeviceProperties,
    EvoOneDeviceProperties,
    SystemType,
    VelisDeviceProperties,
    WheType,
)
from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import UnitOfTemperature

from custom_components.ariston import (
    binary_sensor,
    number,
    select,
    sensor,
    switch,
    water_heater,
)
from custom_components.ariston.const import (
    BUS_ERRORS_COORDINATOR,
    CONF_WATER_HEATER_TEMPERATURE_UNIT_OVERRIDE,
    COORDINATOR,
    DEVICE_FEATURE_DHW_FLAME,
    DEVICE_FEATURE_ZONE_HEAT_REQUEST,
    INSTANTANEOUS_POWER_KEY,
)


@pytest.fixture
def device():
    """Create a VELIS Lux device that exposes the usual features."""
    device = MagicMock()
    device.system_type = SystemType.VELIS
    device.whe_type = WheType.Lux
    device.whe_model_type = 0
    device.name = "Boiler"
    device.gateway = "gw-test"
    device.serial_number = "sn-test"
    device.firmware_version = "1.0"
    device.features = {}
    device.custom_features = {CustomDeviceFeatures.HAS_DHW: True}
    device.attributes = {}
    device.dhw_mode_changeable = True
    device.water_heater_temperature_step = 1
    device.water_heater_power_value = True
    device.is_heating = True

    def _available(device_features=None, system_types=None, whe_types=None):
        if system_types and device.system_type not in system_types:
            return False
        if whe_types and device.whe_type not in whe_types:
            return False
        for feature in device_features or []:
            if not (
                device.features.get(feature)
                or device.custom_features.get(feature)
                or device.attributes.get(feature)
            ):
                return False
        return True

    device.are_device_features_available.side_effect = _available
    return device


@pytest.fixture
def coordinator(device):
    """Create a coordinator exposing the mock device."""
    coordinator = MagicMock()
    coordinator.device = device
    coordinator.rated_power_w = None
    coordinator.config_entry.options = {}
    return coordinator


@pytest.fixture
def hass():
    """Create a minimal Home Assistant object."""
    return MagicMock()


@pytest.fixture
def entry(coordinator):
    """Create a config entry for a device without metering."""
    entry = MagicMock()
    entry.unique_id = "entry-id"
    entry.options = {}
    entry.runtime_data = {
        COORDINATOR: coordinator,
        BUS_ERRORS_COORDINATOR: coordinator,
    }
    return entry


def _created(async_add_entities) -> list:
    return async_add_entities.call_args.args[0]


async def test_sensor_setup_creates_velis_entities(hass, entry, coordinator):
    """VELIS sensors are created, metering sensors are not."""
    async_add_entities = MagicMock()

    await sensor.async_setup_entry(hass, entry, async_add_entities)

    keys = [entity.entity_description.key for entity in _created(async_add_entities)]
    assert EvoOneDeviceProperties.TEMP in keys
    assert EvoLydosDeviceProperties.REQ_TEMP in keys
    assert EvoDeviceProperties.RM_TM in keys
    # No metering feature on this device.
    assert "Domestic hot water electricity consumption" not in keys


@pytest.mark.parametrize("platform", [sensor, number, select])
async def test_platforms_skip_metering_entities_without_energy_coordinator(
    hass, entry, platform
):
    """Platforms must not fail when the optional energy coordinator is absent."""
    async_add_entities = MagicMock()

    await platform.async_setup_entry(hass, entry, async_add_entities)

    async_add_entities.assert_called_once()


async def test_power_sensor_requires_rated_power(hass, entry, coordinator):
    """The estimated power sensor is only created when rated power is set."""
    async_add_entities = MagicMock()

    await sensor.async_setup_entry(hass, entry, async_add_entities)
    keys = [entity.entity_description.key for entity in _created(async_add_entities)]
    assert INSTANTANEOUS_POWER_KEY not in keys

    coordinator.rated_power_w = 1500
    async_add_entities.reset_mock()

    await sensor.async_setup_entry(hass, entry, async_add_entities)
    keys = [entity.entity_description.key for entity in _created(async_add_entities)]
    assert INSTANTANEOUS_POWER_KEY in keys


async def test_binary_sensor_setup_includes_anti_legionella(hass, entry):
    """Lux/Lux2 expose both heating and anti-legionella binary sensors."""
    async_add_entities = MagicMock()

    await binary_sensor.async_setup_entry(hass, entry, async_add_entities)

    keys = [entity.entity_description.key for entity in _created(async_add_entities)]
    assert EvoLydosDeviceProperties.HEAT_REQ in keys
    assert EvoLydosDeviceProperties.ANTI_LEG in keys


async def test_binary_sensor_setup_adds_galevo_diagnostics(hass, entry, coordinator):
    """GALEVO devices get zoned CH heat request and estimated DHW flame sensors."""
    device = coordinator.device
    device.system_type = SystemType.GALEVO
    device.whe_type = WheType.Unknown
    device.zone_numbers = [1, 2]
    device.get_zone_heat_request_value.side_effect = lambda zone: zone == 1

    async_add_entities = MagicMock()
    await binary_sensor.async_setup_entry(hass, entry, async_add_entities)

    entities = _created(async_add_entities)
    heat_requests = [
        entity
        for entity in entities
        if entity.entity_description.key == DEVICE_FEATURE_ZONE_HEAT_REQUEST
    ]
    assert [entity.zone for entity in heat_requests] == [1, 2]
    assert heat_requests[0].name == f"{heat_requests[0].entity_description.name} 1"
    assert heat_requests[0].unique_id == (
        f"gw-test-{DEVICE_FEATURE_ZONE_HEAT_REQUEST}-1"
    )
    assert heat_requests[0].is_on is True
    assert heat_requests[1].is_on is False

    dhw_flames = [
        entity
        for entity in entities
        if entity.entity_description.key == DEVICE_FEATURE_DHW_FLAME
    ]
    assert len(dhw_flames) == 1
    assert dhw_flames[0].entity_description.entity_registry_enabled_default is False


async def test_switch_setup_includes_power(hass, entry):
    """The VELIS power switch is created."""
    async_add_entities = MagicMock()

    await switch.async_setup_entry(hass, entry, async_add_entities)

    keys = [entity.entity_description.key for entity in _created(async_add_entities)]
    assert VelisDeviceProperties.ON in keys


async def test_water_heater_setup_and_attributes(hass, entry):
    """The water heater is created and reports power/heating attributes."""
    async_add_entities = MagicMock()

    await water_heater.async_setup_entry(hass, entry, async_add_entities)

    entities = _created(async_add_entities)
    assert len(entities) == 1
    entity = entities[0]
    assert entity.supported_features & WaterHeaterEntityFeature.ON_OFF

    attributes = entity.extra_state_attributes
    assert attributes["power"] == "on"
    assert attributes["heating"] is True


def _temperature_attribute(entity, name):
    """Read the temperature property exposed by the current HA API."""
    native_name = f"native_{name}"
    if hasattr(type(entity), native_name):
        return getattr(entity, native_name)
    return getattr(entity, name)


async def test_water_heater_temperature_override_uses_ha_api(hass, entry, coordinator):
    """The unit override converts readings and writes through the HA API."""
    device = coordinator.device
    device.water_heater_temperature_unit = UnitOfTemperature.FAHRENHEIT
    device.water_heater_current_temperature = 122.0
    device.water_heater_target_temperature = 140.0
    device.water_heater_minimum_temperature = 100.0
    device.water_heater_maximum_temperature = 150.0
    device.water_heater_temperature_decimals = 1
    device.async_set_water_heater_temperature = AsyncMock()
    coordinator.pending_writes = {}
    coordinator.config_entry.options = {
        CONF_WATER_HEATER_TEMPERATURE_UNIT_OVERRIDE: "celsius"
    }

    async_add_entities = MagicMock()
    await water_heater.async_setup_entry(hass, entry, async_add_entities)
    entity = _created(async_add_entities)[0]

    assert _temperature_attribute(entity, "temperature_unit") == (
        UnitOfTemperature.CELSIUS
    )
    assert _temperature_attribute(entity, "current_temperature") == pytest.approx(50.0)
    assert _temperature_attribute(entity, "target_temperature") == pytest.approx(60.0)
    assert entity.min_temp == pytest.approx((100 - 32) * 5 / 9)
    assert entity.max_temp == pytest.approx((150 - 32) * 5 / 9)
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_temperature(temperature=60.0)

    device.async_set_water_heater_temperature.assert_awaited_once_with(140.0)
    assert coordinator.pending_writes["temperature"].expected == 140.0

    if hasattr(WaterHeaterEntity, "native_temperature_unit"):
        assert "native_temperature_unit" in vars(water_heater.AristonWaterHeater)
        assert "temperature_unit" not in vars(water_heater.AristonWaterHeater)


async def test_water_heater_auto_unit_keeps_device_values(hass, entry, coordinator):
    """Without an override, readings and writes stay in the device unit."""
    device = coordinator.device
    device.water_heater_temperature_unit = UnitOfTemperature.FAHRENHEIT
    device.water_heater_current_temperature = 122.0
    device.water_heater_target_temperature = 140.0
    device.water_heater_temperature_decimals = 1
    device.async_set_water_heater_temperature = AsyncMock()
    coordinator.pending_writes = {}
    coordinator.config_entry.options = {}

    async_add_entities = MagicMock()
    await water_heater.async_setup_entry(hass, entry, async_add_entities)
    entity = _created(async_add_entities)[0]

    assert _temperature_attribute(entity, "temperature_unit") == (
        UnitOfTemperature.FAHRENHEIT
    )
    assert _temperature_attribute(entity, "current_temperature") == 122.0
    assert _temperature_attribute(entity, "target_temperature") == 140.0
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_temperature(temperature=140.0)

    device.async_set_water_heater_temperature.assert_awaited_once_with(140.0)
