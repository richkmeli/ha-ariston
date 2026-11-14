"""The Ariston integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_ID,
    CONF_DEVICE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.util.unit_system import METRIC_SYSTEM

from ariston import Ariston, DeviceAttribute, SystemType
from ariston.ariston_api import ConnectionException
from ariston.base_device import AristonBaseDevice
from ariston.const import ARISTON_API_URL, ARISTON_USER_AGENT

from .const import (
    API_URL_SETTING,
    API_USER_AGENT,
    BUS_ERRORS_COORDINATOR,
    BUS_ERRORS_SCAN_INTERVAL,
    COORDINATOR,
    DEFAULT_BUS_ERRORS_SCAN_INTERVAL_SECONDS,
    DEFAULT_ENERGY_SCAN_INTERVAL_MINUTES,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    ENERGY_COORDINATOR,
    ENERGY_SCAN_INTERVAL,
    MIN_BUS_ERRORS_SCAN_INTERVAL_SECONDS,
    MIN_ENERGY_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_SECONDS,
    RATED_POWER_W,
)
from .coordinator import DeviceDataUpdateCoordinator, is_auth_error
from .entity import async_migrate_entity_unique_ids

_LOGGER = logging.getLogger(__name__)

type AristonConfigEntry = ConfigEntry[dict[str, DeviceDataUpdateCoordinator]]

# Config schema for config entry only integration
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.WATER_HEATER,
]


SERVICE_CREATE_VACATION = "create_vacation"
SERVICE_SET_ITEM_BY_ID = "set_item_by_id"
ATTR_END_DATE = "end_date"
ATTR_ITEM_ID = "item_id"
ATTR_ZONE = "zone"
ATTR_VALUE = "value"

CREATE_VACATION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_END_DATE): cv.date,
    }
)

SET_ITEM_BY_ID_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_ITEM_ID): cv.string,
        vol.Required(ATTR_ZONE): vol.All(cv.positive_int, vol.Range(min=1)),
        vol.Required(ATTR_VALUE): vol.Coerce(float),
    }
)


def _async_get_target_coordinator(
    hass: HomeAssistant, device_id: str
) -> DeviceDataUpdateCoordinator:
    """Resolve a GALEVO coordinator from a device registry id."""
    device_entry = dr.async_get(hass).async_get(device_id)
    if device_entry is None:
        raise ServiceValidationError("Device not found")

    entry_id = next(iter(device_entry.config_entries), None)
    target_entry = (
        hass.config_entries.async_get_entry(entry_id) if entry_id is not None else None
    )
    if target_entry is None or target_entry.runtime_data is None:
        raise ServiceValidationError("Device entry is not loaded")

    coordinator = target_entry.runtime_data.get(COORDINATOR)
    if coordinator is None:
        raise ServiceValidationError("Device entry is not loaded")
    if coordinator.device.system_type != SystemType.GALEVO:
        raise ServiceValidationError("Service is only supported on GALEVO devices")
    return coordinator


def _async_migrate_device_identifier(
    hass: HomeAssistant, device: AristonBaseDevice
) -> None:
    """Move legacy serial/empty device identifiers to the gateway.

    Devices without a serial number used to share the ``(ariston, "")``
    identifier, merging unrelated devices into one registry entry.  The
    gateway is always available and unique per physical device.  Existing
    devices are migrated in place so areas, names and entity links survive.
    """
    gateway = device.gateway
    if not gateway:
        return

    registry = dr.async_get(hass)
    gateway_identifier = (DOMAIN, gateway)
    if registry.async_get_device(identifiers={gateway_identifier}) is not None:
        return

    legacy_identifier = (DOMAIN, device.serial_number or "")
    legacy_device = registry.async_get_device(identifiers={legacy_identifier})
    if legacy_device is None:
        return

    new_identifiers = {
        identifier
        for identifier in legacy_device.identifiers
        if identifier != (DOMAIN, "")
    }
    new_identifiers.add(gateway_identifier)
    registry.async_update_device(
        legacy_device.id,
        new_identifiers=new_identifiers,
    )


def _async_register_galevo_services(hass: HomeAssistant) -> None:
    """Register services that are available on GALEVO devices once."""

    async def async_create_vacation_service(service_call) -> None:
        """Create or clear a vacation on the target device."""
        coordinator = _async_get_target_coordinator(
            hass, service_call.data[ATTR_DEVICE_ID]
        )
        await coordinator.device.async_set_holiday(service_call.data.get(ATTR_END_DATE))
        await coordinator.async_request_refresh()

    async def async_set_item_by_id_service(service_call) -> None:
        """Set a raw device or thermostat property."""
        coordinator = _async_get_target_coordinator(
            hass, service_call.data[ATTR_DEVICE_ID]
        )
        await coordinator.device.async_set_item_by_id(
            service_call.data[ATTR_ITEM_ID],
            service_call.data[ATTR_VALUE],
            service_call.data[ATTR_ZONE],
        )
        await coordinator.async_request_refresh()

    if not hass.services.has_service(DOMAIN, SERVICE_CREATE_VACATION):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CREATE_VACATION,
            async_create_vacation_service,
            schema=CREATE_VACATION_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SET_ITEM_BY_ID):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_ITEM_BY_ID,
            async_set_item_by_id_service,
            schema=SET_ITEM_BY_ID_SCHEMA,
        )


def _async_remove_galevo_services(hass: HomeAssistant) -> None:
    """Remove GALEVO services when no GALEVO entry remains loaded."""
    for service in (SERVICE_CREATE_VACATION, SERVICE_SET_ITEM_BY_ID):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


def _entry_has_galevo_device(entry: ConfigEntry) -> bool:
    """Return whether a loaded entry still exposes a GALEVO device."""
    coordinators = getattr(entry, "runtime_data", None)
    if not coordinators:
        return False
    coordinator = coordinators.get(COORDINATOR)
    return (
        coordinator is not None and coordinator.device.system_type == SystemType.GALEVO
    )


def _get_option_interval(
    entry: AristonConfigEntry, key: str, default: int, minimum: int
) -> int:
    """Return a validated interval from the entry options."""
    value = entry.options.get(key, default)
    try:
        interval = int(value)
    except (TypeError, ValueError):
        _LOGGER.warning("Ignoring invalid %s option: %s", key, value)
        return default

    if interval < minimum:
        _LOGGER.warning(
            "Ignoring %s option below the minimum of %s: %s",
            key,
            minimum,
            value,
        )
        return default
    return interval


async def async_setup_entry(hass: HomeAssistant, entry: AristonConfigEntry) -> bool:
    """Set up Ariston from a config entry."""
    ariston = Ariston()
    try:
        api_url_setting = entry.data.get(API_URL_SETTING, ARISTON_API_URL)

        api_user_agent = entry.data.get(API_USER_AGENT, ARISTON_USER_AGENT)

        response = await ariston.async_connect(
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            api_url_setting,
            api_user_agent,
        )
        if not response:
            _LOGGER.error(
                "Failed to connect to Ariston with device: %s",
                entry.data[CONF_DEVICE].get(DeviceAttribute.NAME),
            )
            raise ConfigEntryAuthFailed

        device = await ariston.async_hello(
            entry.data[CONF_DEVICE].get(DeviceAttribute.GW),
            hass.config.units is METRIC_SYSTEM,
        )
        if device is None:
            raise ConfigEntryNotReady(
                f"Device {entry.data[CONF_DEVICE].get(DeviceAttribute.NAME)} "
                "was not found"
            )

        try:
            await device.async_get_features()
        except Exception as err:
            # VELIS devices load plant settings inside async_get_features; a
            # failing settings endpoint must not block the whole setup, because
            # the coordinator retries the refresh in the background.
            if not getattr(device, "features", None):
                raise
            _LOGGER.warning(
                "Unable to read plant settings for %s, will retry later: %s",
                device.name,
                err,
            )

        scan_interval_seconds = _get_option_interval(
            entry,
            CONF_SCAN_INTERVAL,
            DEFAULT_SCAN_INTERVAL_SECONDS,
            MIN_SCAN_INTERVAL_SECONDS,
        )
        coordinator = DeviceDataUpdateCoordinator(
            hass,
            entry,
            device,
            scan_interval_seconds,
            COORDINATOR,
            device.async_update_state,
        )
        rated_power_w = entry.options.get(RATED_POWER_W)
        try:
            coordinator.rated_power_w = (
                int(rated_power_w) if rated_power_w not in (None, "") else None
            )
        except (TypeError, ValueError):
            _LOGGER.warning("Ignoring invalid rated power option: %s", rated_power_w)
            coordinator.rated_power_w = None

        await coordinator.async_config_entry_first_refresh()

        # Migrate registry data after the first poll, when features and zones
        # are populated, but before platforms register their entities.
        _async_migrate_device_identifier(hass, device)
        await async_migrate_entity_unique_ids(hass, entry, device)

        coordinators: dict[str, DeviceDataUpdateCoordinator] = {
            COORDINATOR: coordinator
        }

        bus_errors_scan_interval_seconds = _get_option_interval(
            entry,
            BUS_ERRORS_SCAN_INTERVAL,
            DEFAULT_BUS_ERRORS_SCAN_INTERVAL_SECONDS,
            MIN_BUS_ERRORS_SCAN_INTERVAL_SECONDS,
        )
        bus_errors_coordinator = DeviceDataUpdateCoordinator(
            hass,
            entry,
            device,
            bus_errors_scan_interval_seconds,
            BUS_ERRORS_COORDINATOR,
            device.async_get_bus_errors,
        )
        coordinators[BUS_ERRORS_COORDINATOR] = bus_errors_coordinator
        # Bus errors are diagnostic data: a failing endpoint must not block setup.
        await bus_errors_coordinator.async_refresh()

        if device.has_metering:
            energy_interval_minutes = _get_option_interval(
                entry,
                ENERGY_SCAN_INTERVAL,
                DEFAULT_ENERGY_SCAN_INTERVAL_MINUTES,
                MIN_ENERGY_SCAN_INTERVAL_MINUTES,
            )
            energy_coordinator = DeviceDataUpdateCoordinator(
                hass,
                entry,
                device,
                energy_interval_minutes * 60,
                ENERGY_COORDINATOR,
                device.async_update_energy,
            )
            coordinators[ENERGY_COORDINATOR] = energy_coordinator
            # Energy data is optional: do not fail setup if the endpoint is down.
            await energy_coordinator.async_refresh()

        entry.runtime_data = coordinators
        try:
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        except Exception:
            entry.runtime_data = None
            raise

        entry.async_on_unload(entry.add_update_listener(update_listener))

        if device.system_type == SystemType.GALEVO:
            _async_register_galevo_services(hass)
    except ConfigEntryAuthFailed:
        raise
    except ConfigEntryNotReady:
        raise
    except ConnectionException as error:
        if is_auth_error(error):
            _LOGGER.error("Authentication error during setup: %s", error)
            raise ConfigEntryAuthFailed from error
        _LOGGER.error("Connection error during setup: %s", error)
        raise ConfigEntryNotReady from error
    except TimeoutError as error:
        _LOGGER.error("Timeout during setup: %s", error)
        raise ConfigEntryNotReady from error
    except Exception:
        _LOGGER.exception("Unexpected error during setup")
        raise

    return True


async def update_listener(hass: HomeAssistant, entry: AristonConfigEntry) -> None:
    """Update listener."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AristonConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        entry.runtime_data = None
        remaining_galevo_entries = any(
            _entry_has_galevo_device(candidate)
            for candidate in hass.config_entries.async_entries(DOMAIN)
            if candidate.entry_id != entry.entry_id
        )
        if not remaining_galevo_entries:
            _async_remove_galevo_services(hass)

    return unload_ok
