"""Support for Ariston sensors."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from ariston.const import DeviceProperties, SystemType

from . import AristonConfigEntry
from .const import (
    ARISTON_BINARY_SENSOR_TYPES,
    COORDINATOR,
    DOMAIN,
    AristonBinarySensorEntityDescription,
)
from .coordinator import DeviceDataUpdateCoordinator
from .entity import AristonEntity

_LOGGER = logging.getLogger(__name__)

SERVICE_CREATE_VACATION = "create_vacation"
ATTR_END_DATE = "end_date"

CREATE_VACATION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_END_DATE): cv.date,
    }
)


async def async_setup_entry(
    hass: HomeAssistant, entry: AristonConfigEntry, async_add_entities
) -> None:
    """Set up the Ariston binary sensors from config entry."""
    ariston_binary_sensors: list[AristonBinarySensor] = []
    for description in ARISTON_BINARY_SENSOR_TYPES:
        coordinator: DeviceDataUpdateCoordinator = entry.runtime_data[
            description.coordinator
        ]
        if (
            coordinator
            and coordinator.device
            and coordinator.device.are_device_features_available(
                description.device_features,
                description.system_types,
                description.whe_types,
            )
        ):
            ariston_binary_sensors.append(AristonBinarySensor(coordinator, description))

    async_add_entities(ariston_binary_sensors)

    if coordinator.device.system_type == SystemType.GALEVO:

        async def async_create_vacation_service(service_call):
            """Create a vacation on the target device."""
            device_id = service_call.data.get(ATTR_DEVICE_ID)
            end_date = service_call.data.get(ATTR_END_DATE)

            device_registry = dr.async_get(hass)
            device = device_registry.async_get(device_id)
            if device is None:
                raise ServiceValidationError("Device not found")

            entry_id = next(iter(device.config_entries), None)
            target_entry = (
                hass.config_entries.async_get_entry(entry_id)
                if entry_id is not None
                else None
            )
            if target_entry is None or target_entry.runtime_data is None:
                raise ServiceValidationError("Device entry is not loaded")
            coordinator: DeviceDataUpdateCoordinator = target_entry.runtime_data[
                COORDINATOR
            ]
            await coordinator.device.async_set_holiday(end_date)
            for ariston_binary_sensor in ariston_binary_sensors:
                if (
                    ariston_binary_sensor.entity_description.key
                    is DeviceProperties.HOLIDAY
                ):
                    ariston_binary_sensor.async_write_ha_state()

        hass.services.async_register(
            DOMAIN,
            SERVICE_CREATE_VACATION,
            async_create_vacation_service,
            schema=CREATE_VACATION_SCHEMA,
        )


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
