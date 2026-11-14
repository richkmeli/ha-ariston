"""Tests for Ariston config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from ariston.ariston_api import ConnectionException
from homeassistant.const import CONF_SCAN_INTERVAL

from custom_components.ariston.config_flow import (
    STEP_USER_DATA_SCHEMA,
    AristonConfigFlow,
    AristonOptionsFlow,
)
from custom_components.ariston.const import (
    BUS_ERRORS_SCAN_INTERVAL,
    ENERGY_SCAN_INTERVAL,
    MIN_BUS_ERRORS_SCAN_INTERVAL_SECONDS,
    MIN_ENERGY_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_SECONDS,
)


@pytest.fixture
def config_flow():
    """Create a config flow instance."""
    flow = AristonConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config_entries = MagicMock()
    flow.hass.config_entries.async_entry_for_domain_unique_id = MagicMock(
        return_value=None
    )
    flow.hass.config_entries.async_reload = AsyncMock()
    # The flow manager normally initializes the context before running a flow.
    flow.context = {"source": "user"}
    return flow


def test_step_user_data_schema():
    """Test the user step data schema."""
    schema = STEP_USER_DATA_SCHEMA
    assert "username" in schema.schema
    assert "password" in schema.schema
    assert "api_url_setting" in schema.schema
    assert "api_user_agent" in schema.schema


async def test_async_step_user_success(config_flow):
    """Test successful user step."""
    user_input = {
        "username": "test@example.com",
        "password": "password123",
        "api_url_setting": "https://api.ariston.com",
        "api_user_agent": "TestAgent/1.0",
    }

    with patch("custom_components.ariston.config_flow.Ariston") as mock_ariston_class:
        mock_ariston = AsyncMock()
        mock_ariston_class.return_value = mock_ariston
        mock_ariston.async_connect = AsyncMock(return_value=True)
        mock_ariston.async_discover = AsyncMock(
            return_value=[{"gw": "gateway123", "name": "Test Device", "sn": "SN123"}]
        )

        result = await config_flow.async_step_user(user_input)

        assert result["type"] == "create_entry"
        assert result["title"] == "Test Device"
        assert result["data"]["username"] == "test@example.com"


async def test_async_step_user_invalid_auth(config_flow):
    """Test user step with invalid auth."""
    user_input = {
        "username": "test@example.com",
        "password": "wrongpassword",
        "api_url_setting": "https://api.ariston.com",
        "api_user_agent": "TestAgent/1.0",
    }

    with patch("custom_components.ariston.config_flow.Ariston") as mock_ariston_class:
        mock_ariston = AsyncMock()
        mock_ariston_class.return_value = mock_ariston
        mock_ariston.async_connect = AsyncMock(return_value=False)

        result = await config_flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["errors"]["base"] == "invalid_auth"


async def test_async_step_user_connection_error(config_flow):
    """Test user step with connection error."""
    user_input = {
        "username": "test@example.com",
        "password": "password123",
        "api_url_setting": "https://api.ariston.com",
        "api_user_agent": "TestAgent/1.0",
    }

    with patch("custom_components.ariston.config_flow.Ariston") as mock_ariston_class:
        mock_ariston = AsyncMock()
        mock_ariston_class.return_value = mock_ariston
        mock_ariston.async_connect = AsyncMock(
            side_effect=ConnectionException("Connection failed")
        )

        result = await config_flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["errors"]["base"] == "cannot_connect"


async def test_async_step_user_auth_connection_error(config_flow):
    """A login failure reported as an exception shows invalid_auth."""
    user_input = {
        "username": "test@example.com",
        "password": "wrongpassword",
        "api_url_setting": "https://api.ariston.com",
        "api_user_agent": "TestAgent/1.0",
    }

    with patch("custom_components.ariston.config_flow.Ariston") as mock_ariston_class:
        mock_ariston = AsyncMock()
        mock_ariston_class.return_value = mock_ariston
        mock_ariston.async_connect = AsyncMock(
            side_effect=ConnectionException("Login failed")
        )

        result = await config_flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["errors"]["base"] == "invalid_auth"


async def test_async_step_user_discovery_connection_error(config_flow):
    """A failure while listing devices must be reported, not raised."""
    user_input = {
        "username": "test@example.com",
        "password": "password123",
        "api_url_setting": "https://api.ariston.com",
        "api_user_agent": "TestAgent/1.0",
    }

    with patch("custom_components.ariston.config_flow.Ariston") as mock_ariston_class:
        mock_ariston = AsyncMock()
        mock_ariston_class.return_value = mock_ariston
        mock_ariston.async_connect = AsyncMock(return_value=True)
        mock_ariston.async_discover = AsyncMock(
            side_effect=ConnectionException("Connection failed")
        )

        result = await config_flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["errors"]["base"] == "cannot_connect"


async def test_async_step_user_no_devices(config_flow):
    """Test user step when no devices found."""
    user_input = {
        "username": "test@example.com",
        "password": "password123",
        "api_url_setting": "https://api.ariston.com",
        "api_user_agent": "TestAgent/1.0",
    }

    with patch("custom_components.ariston.config_flow.Ariston") as mock_ariston_class:
        mock_ariston = AsyncMock()
        mock_ariston_class.return_value = mock_ariston
        mock_ariston.async_connect = AsyncMock(return_value=True)
        mock_ariston.async_discover = AsyncMock(return_value=[])

        result = await config_flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["errors"]["base"] == "no_device_found"


async def test_async_step_user_multiple_devices(config_flow):
    """Test user step with multiple devices."""
    user_input = {
        "username": "test@example.com",
        "password": "password123",
        "api_url_setting": "https://api.ariston.com",
        "api_user_agent": "TestAgent/1.0",
    }

    with patch("custom_components.ariston.config_flow.Ariston") as mock_ariston_class:
        mock_ariston = AsyncMock()
        mock_ariston_class.return_value = mock_ariston
        mock_ariston.async_connect = AsyncMock(return_value=True)
        mock_ariston.async_discover = AsyncMock(
            return_value=[
                {"gw": "gateway1", "name": "Device 1", "sn": "SN1"},
                {"gw": "gateway2", "name": "Device 2", "sn": "SN2"},
            ]
        )

        result = await config_flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["step_id"] == "select"
        assert "select_device" in result["data_schema"].schema


async def test_async_step_reauth_updates_its_own_entry(config_flow):
    """Reauth updates the entry that requested it, not another gateway entry."""
    config_flow.context = {"source": "reauth", "entry_id": "entry-id"}
    reauth_entry = MagicMock()
    reauth_entry.unique_id = "gateway2"
    reauth_entry.entry_id = "entry-id"
    reauth_entry.data = {
        "username": "old@example.com",
        "password": "old-password",
        "api_url_setting": "https://old.example.com",
        "api_user_agent": "OldAgent/1.0",
        "device": {"gw": "gateway2", "name": "Old Device"},
    }
    config_flow.hass.config_entries.async_get_known_entry = MagicMock(
        return_value=reauth_entry
    )

    user_input = {
        "username": "new@example.com",
        "password": "new-password",
        "api_url_setting": "https://api.ariston.com",
        "api_user_agent": "TestAgent/1.0",
    }

    with patch("custom_components.ariston.config_flow.Ariston") as mock_ariston_class:
        mock_ariston = AsyncMock()
        mock_ariston_class.return_value = mock_ariston
        mock_ariston.async_connect = AsyncMock(return_value=True)
        mock_ariston.async_discover = AsyncMock(
            return_value=[
                {"gw": "gateway1", "name": "Other Device", "sn": "SN1"},
                {"gw": "gateway2", "name": "Device 2", "sn": "SN2"},
            ]
        )

        result = await config_flow.async_step_user(user_input)

    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    config_flow.hass.config_entries.async_update_entry.assert_called_once()
    call = config_flow.hass.config_entries.async_update_entry.call_args
    assert call.args[0] is reauth_entry
    assert call.kwargs["data"]["username"] == "new@example.com"
    assert call.kwargs["data"]["password"] == "new-password"
    assert call.kwargs["data"]["device"]["gw"] == "gateway2"
    config_flow.hass.config_entries.async_reload.assert_awaited_once_with("entry-id")


async def test_async_step_reauth_requires_its_gateway(config_flow):
    """Reauth does not switch the entry to a different discovered device."""
    config_flow.context = {"source": "reauth", "entry_id": "entry-id"}
    reauth_entry = MagicMock()
    reauth_entry.unique_id = "gateway1"
    reauth_entry.entry_id = "entry-id"
    reauth_entry.data = {"device": {"gw": "gateway1", "name": "Device 1"}}
    config_flow.hass.config_entries.async_get_known_entry = MagicMock(
        return_value=reauth_entry
    )

    user_input = {
        "username": "test@example.com",
        "password": "password123",
        "api_url_setting": "https://api.ariston.com",
        "api_user_agent": "TestAgent/1.0",
    }

    with patch("custom_components.ariston.config_flow.Ariston") as mock_ariston_class:
        mock_ariston = AsyncMock()
        mock_ariston_class.return_value = mock_ariston
        mock_ariston.async_connect = AsyncMock(return_value=True)
        mock_ariston.async_discover = AsyncMock(
            return_value=[{"gw": "gateway2", "name": "Device 2", "sn": "SN2"}]
        )

        result = await config_flow.async_step_user(user_input)

    assert result["type"] == "form"
    assert result["errors"]["base"] == "no_device_found"
    config_flow.hass.config_entries.async_update_entry.assert_not_called()


async def test_options_flow_clamps_defaults_and_enforces_minimums():
    """Old or invalid intervals are clamped and short values are rejected."""
    flow = AristonOptionsFlow()
    flow.hass = MagicMock()
    flow.handler = "entry-id"
    entry = MagicMock()
    entry.options = {
        CONF_SCAN_INTERVAL: 1,
        ENERGY_SCAN_INTERVAL: 0,
        BUS_ERRORS_SCAN_INTERVAL: 5,
    }
    flow.hass.config_entries.async_get_known_entry = MagicMock(return_value=entry)

    result = await flow.async_step_init()
    schema = result["data_schema"]

    data = schema({})
    assert data[CONF_SCAN_INTERVAL] == MIN_SCAN_INTERVAL_SECONDS
    assert data[ENERGY_SCAN_INTERVAL] == MIN_ENERGY_SCAN_INTERVAL_MINUTES
    assert data[BUS_ERRORS_SCAN_INTERVAL] == MIN_BUS_ERRORS_SCAN_INTERVAL_SECONDS

    with pytest.raises(vol.Invalid):
        schema({CONF_SCAN_INTERVAL: MIN_SCAN_INTERVAL_SECONDS - 1})
    with pytest.raises(vol.Invalid):
        schema({ENERGY_SCAN_INTERVAL: MIN_ENERGY_SCAN_INTERVAL_MINUTES - 1})
    with pytest.raises(vol.Invalid):
        schema({BUS_ERRORS_SCAN_INTERVAL: MIN_BUS_ERRORS_SCAN_INTERVAL_SECONDS - 1})
