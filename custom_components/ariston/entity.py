"""Entity object for shared properties of Ariston entities."""

from __future__ import annotations

import logging
from abc import ABC

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ariston.base_device import AristonBaseDevice
from ariston.const import WheType

from .const import (
    ARISTON_BINARY_SENSOR_TYPES,
    ARISTON_NUMBER_TYPES,
    ARISTON_SELECT_TYPES,
    ARISTON_SENSOR_TYPES,
    ARISTON_SWITCH_TYPES,
    DOMAIN,
    EXTRA_STATE_ATTRIBUTE,
    EXTRA_STATE_DEVICE_METHOD,
    NAME,
    AristonBaseEntityDescription,
)
from .coordinator import DeviceDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entity_unique_ids(
    hass: HomeAssistant, entry: ConfigEntry, device: AristonBaseDevice
) -> None:
    """Migrate legacy name-based unique IDs to stable description keys.

    The previous scheme used the entity name, which is user-facing and can
    change.  New IDs are based on the description key and zone instead.  The
    entity registry is migrated before platforms are set up, so entity IDs,
    history and customisations are preserved.
    """
    gateway = device.gateway
    if not gateway:
        return

    zone_numbers = getattr(device, "zone_numbers", None) or []

    legacy_to_new: dict[str, str] = {}
    for descriptions in (
        ARISTON_SENSOR_TYPES,
        ARISTON_BINARY_SENSOR_TYPES,
        ARISTON_NUMBER_TYPES,
        ARISTON_SELECT_TYPES,
        ARISTON_SWITCH_TYPES,
    ):
        for description in descriptions:
            if description.zone:
                for zone in zone_numbers:
                    legacy_to_new[f"{gateway}-{description.name} {zone}-{zone}"] = (
                        f"{gateway}-{description.key}-{zone}"
                    )
            else:
                legacy_to_new[f"{gateway}-{description.name}"] = (
                    f"{gateway}-{description.key}"
                )

    for zone in zone_numbers:
        legacy_to_new[f"{gateway}_{zone}"] = f"{gateway}-AristonClimate-{zone}"

    def _migrate(registry_entry: er.RegistryEntry) -> dict[str, str] | None:
        new_unique_id = legacy_to_new.get(registry_entry.unique_id)
        if new_unique_id is None or new_unique_id == registry_entry.unique_id:
            return None
        if (
            er.async_get(hass).async_get_entity_id(
                registry_entry.domain,
                registry_entry.platform,
                new_unique_id,
            )
            is not None
        ):
            _LOGGER.warning(
                "Cannot migrate %s to unique ID %s: it already exists",
                registry_entry.entity_id,
                new_unique_id,
            )
            return None
        return {"new_unique_id": new_unique_id}

    await er.async_migrate_entries(hass, entry.entry_id, _migrate)


class AristonEntity(CoordinatorEntity, ABC):
    """Generic Ariston entity (base class)."""

    def __init__(
        self,
        coordinator: DeviceDataUpdateCoordinator,
        description: AristonBaseEntityDescription,
        zone: int = 0,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)

        self.device = coordinator.device
        self.entity_description: AristonBaseEntityDescription = description
        self.zone = zone

    @property
    def device_info(self) -> DeviceInfo:
        """Return device specific attributes."""
        identifiers: set[tuple[str, str]] = set()
        if self.device.gateway:
            identifiers.add((DOMAIN, self.device.gateway))
        if self.device.serial_number:
            identifiers.add((DOMAIN, self.device.serial_number))
        return DeviceInfo(
            identifiers=identifiers,
            manufacturer="Ariston",
            name=self.device.name or NAME,
            sw_version=self.device.firmware_version,
            model=self.model,
        )

    @property
    def model(self) -> str:
        """Return the model of the entity."""
        if self.device.whe_model_type == 0:
            if self.device.whe_type is WheType.Unknown:
                return f"{self.device.system_type.name}"
            return f"{self.device.system_type.name} {self.device.whe_type.name}"
        return f"{self.device.system_type.name} {self.device.whe_type.name} | Model {self.device.whe_model_type}"

    @property
    def extra_state_attributes(self):
        """Return the holiday end date."""
        state_attributes = {}

        if self.entity_description.extra_states is None:
            return None

        for extra_state in self.entity_description.extra_states:
            device_method = extra_state.get(EXTRA_STATE_DEVICE_METHOD)

            if device_method is None:
                continue

            state_attribute = device_method(self)

            if state_attribute is None:
                continue

            state_attributes[extra_state.get(EXTRA_STATE_ATTRIBUTE)] = state_attribute

        return state_attributes

    @property
    def unique_id(self):
        """Return the stable unique id."""
        if self.zone:
            return f"{self.device.gateway}-{self.entity_description.key}-{self.zone}"
        return f"{self.device.gateway}-{self.entity_description.key}"
