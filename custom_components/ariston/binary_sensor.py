"""Support for Ariston sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant

from . import AristonConfigEntry
from .const import (
    ARISTON_BINARY_SENSOR_TYPES,
    AristonBinarySensorEntityDescription,
)
from .coordinator import DeviceDataUpdateCoordinator
from .entity import AristonEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AristonConfigEntry, async_add_entities
) -> None:
    """Set up the Ariston binary sensors from config entry."""
    ariston_binary_sensors: list[AristonBinarySensor] = []
    for description in ARISTON_BINARY_SENSOR_TYPES:
        coordinator: DeviceDataUpdateCoordinator | None = entry.runtime_data.get(
            description.coordinator
        )
        if coordinator is None:
            continue
        if coordinator.device and coordinator.device.are_device_features_available(
            description.device_features,
            description.system_types,
            description.whe_types,
        ):
            ariston_binary_sensors.append(AristonBinarySensor(coordinator, description))

    async_add_entities(ariston_binary_sensors)


class AristonBinarySensor(AristonEntity, BinarySensorEntity):
    """Base class for specific ariston binary sensors."""

    def __init__(
        self,
        coordinator: DeviceDataUpdateCoordinator,
        description: AristonBinarySensorEntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, description)

    @property
    def is_on(self):
        """Return True if the binary sensor is on."""
        return self.entity_description.get_is_on(self)
