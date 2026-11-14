# Ariston NET

Home Assistant integration for Ariston NET-compatible heating and water-heating devices. It uses the Ariston API directly and does not scrape the Ariston website.

This is a community fork of [fustom/ariston-remotethermo-home-assistant-v3](https://github.com/fustom/ariston-remotethermo-home-assistant-v3), maintained by [@richkmeli](https://github.com/richkmeli). It is not affiliated with Ariston, Chaffoteaux or Home Assistant.

## Features

- **Direct API** — faster polling and writes than website-based integrations.
- **UI setup** — config flow with re-authentication and options.
- **Platforms** — water heater, climate, sensors, binary sensors, switches, selects and numbers.
- **Energy monitoring** — daily totals for the Energy Dashboard and optional estimated instantaneous power for VELIS devices.
- **Diagnostics** — downloadable dump with credentials, gateway identifiers and geolocation redacted.
- **Services** — `create_vacation` and `set_item_by_id` on supported GALEVO systems.
- **Localization** — English, Italian, Catalan, Russian, Ukrainian, French, Spanish, Portuguese and Polish.

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## Supported devices

The integration has been tested with:

- Ariston Alteas One 24
- Ariston Velis Evo
- Ariston Velis Lux
- Ariston Lydos Hybrid
- Ariston Genus One
- Ariston Nuos Split
- Ariston Thision S
- Chaffoteaux INOA S 24

Other models may work. If your model is not listed, open an issue or pull request with the device model and the diagnostics file.

## Requirements

- Home Assistant 2024.1.0 or newer.
- An Ariston NET account with access to the device.
- Internet access from Home Assistant to the Ariston cloud API.
- A supported heating or water-heating device.

## Installation

### HACS (recommended)

This fork is not in the default HACS store. Add it as a custom repository:

1. Open **HACS → Integrations**.
2. Open the three-dot menu and choose **Custom repositories**.
3. Add `https://github.com/richkmeli/ha-ariston` with category **Integration**.
4. Search for **Ariston NET**, install it and restart Home Assistant.

### Manual

1. Copy `custom_components/ariston` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Add the integration from the Home Assistant UI.

## Configuration

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **Ariston NET**.
3. Enter the username and password of your Ariston NET account.
4. If the account has more than one device, select the device to add.
5. Finish the setup. The integration creates the entities supported by the device.

The advanced **Ariston API URL** and **Ariston API User Agent** fields can normally be left at their defaults. Change them only if you know that the Ariston API endpoint or client identification has changed.

### Options

Open the integration entry and choose **Configure** to change these options:

| Option | Default | Description |
| --- | --- | --- |
| Zone scan interval | 300 seconds | How often the device state is polled. |
| Energy scan interval | 60 minutes | How often consumption data is refreshed on devices with metering. |
| Bus errors scan interval | 900 seconds | How often diagnostic bus errors are refreshed. |
| Water heater temperature unit override | `auto` | `auto`, `celsius` or `fahrenheit`. Use `fahrenheit` if the water heater reports temperatures in the wrong unit. |
| Rated power | empty | Rated power in watts, used for the estimated instantaneous power sensor on VELIS devices. Leave empty to disable the sensor. |

For a Velis Tech 100, set the rated power to `1500` W. The value is an estimate: the sensor reports the rated power while the resistor is heating and zero otherwise.

## Entities

The exact entities depend on the device model and the features reported by the Ariston API. The integration can create:

- **Water heater** — current and target temperature, operation mode and on/off control on supported VELIS models.
- **Climate** — heating zones on GALEVO and BSB systems.
- **Sensors** — temperatures, pressures, energy consumption, signal strength, remaining time and diagnostic values.
- **Binary sensors** — flame, heating pump, holiday mode, heating state, anti-legionella cycle and other device states.
- **Switches** — power, eco mode, anti-legionella, preheating, boost and model-specific options.
- **Selects** — operation mode, hybrid mode, currency and other configuration choices.
- **Numbers** — setpoints, heating flow temperature and model-specific configuration values.

Entity IDs depend on the device name. The examples in this README use `water_heater.ariston` and `switch.ariston_power`; check the actual IDs in **Developer tools → States**.

### Services

The following services are available on supported GALEVO systems:

- `ariston.create_vacation` — create a vacation on a device. Without an end date, the vacation is deleted.
- `ariston.set_item_by_id` — set a raw device or thermostat property. This is an advanced service; prefer the normal entities when possible.

## Energy Dashboard

The cloud reports energy in hourly buckets. The integration exposes **today's total** for each consumption counter. The value is the sum of the hourly samples and resets at local midnight, which is what the Energy Dashboard expects from a `total` sensor.

- If your model reports metering, add the `... energy consumption` or `... electricity consumption` sensors to **Settings → Dashboards → Energy**.
- The instantaneous power sensor is not an energy counter. To use it in the Energy Dashboard, create a **Riemann sum integral** helper in **Settings → Devices & services → Helpers**, using the power sensor as input, and add the resulting kWh sensor to the dashboard.

## Water heater state and the power switch

On VELIS water heaters, `water_heater.ariston` reports the operation mode as its state (`MANUAL`, `PROGRAM`, `BOOST`, and so on). When the boiler is switched off, Home Assistant keeps showing the last mode instead of `off`. This is how the water heater platform works, not a bug in the integration.

On models that expose the power switch, use `switch.ariston_power` when you need a reliable on/off state for dashboards or automations:

```yaml
action: switch.turn_off
target:
  entity_id: switch.ariston_power
```

Since v0.20.10, `switch.ariston_power` and `water_heater.turn_on` / `turn_off` call the same API, and the switch state is refreshed immediately after either call.

## Example automations

### BOOST with excess photovoltaic power

`BOOST` is available on Lux and Lux2 (Velis Tech) devices. It raises the setpoint to the maximum and the boiler returns to the previous mode when the boost ends.

```yaml
automation:
  - alias: "Ariston BOOST on solar surplus"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.solar_export_power
        above: 1200
        for: "00:10:00"
    actions:
      - action: water_heater.set_operation_mode
        target:
          entity_id: water_heater.ariston
        data:
          operation_mode: BOOST

  - alias: "Ariston back to PROGRAM"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.solar_export_power
        below: 200
        for: "00:10:00"
    actions:
      - action: water_heater.set_operation_mode
        target:
          entity_id: water_heater.ariston
        data:
          operation_mode: PROGRAM
```

Replace `sensor.solar_export_power` with your inverter or energy sensor.

### Notify when the tank gets cold

```yaml
automation:
  - alias: "Ariston water temperature low"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.ariston_current_temperature
        below: 40
        for: "00:15:00"
    actions:
      - action: notify.persistent_notification
        data:
          title: "Ariston"
          message: "Water temperature below 40 °C."
```

## Floor plan card

The power switch is the entity whose state is actually `on` or `off`, so its icon colour follows the boiler. Tap toggles the power; hold opens the water heater card with modes and temperatures.

```yaml
type: picture-elements
image: /local/planimetria.png
elements:
  - type: state-icon
    entity: switch.ariston_power
    icon: mdi:water-boiler
    state_color: true
    tap_action:
      action: toggle
    hold_action:
      action: more-info
      entity: water_heater.ariston
    style:
      left: 85%
      top: 74%
```

Replace `/local/planimetria.png` with your own floor-plan image. No dashboard images are bundled with this repository.

If you prefer two separate icons, keep `water_heater.ariston` for the mode and temperature card, and add `switch.ariston_power` on top for the on/off state. Do not use `water_heater.ariston` alone for the colour: its state is always the operation mode, even when the power is off.

## Diagnostics

If something does not work, download a diagnostics dump from **Settings → Devices & services → Ariston → ⋮ → Download diagnostics** and attach it to the issue. Credentials, gateway identifiers and geolocation are redacted automatically. The dump contains the device type, features, plant settings, raw state and consumption sequences.

## Troubleshooting

### The integration disappeared after an update

If Home Assistant logs `No setup or config entry setup function defined`, or the integration is no longer listed, check the installed layout:

```bash
ls /config/custom_components/ariston
```

You should see `__init__.py` and `manifest.json` directly in that folder. If there is another `ariston/` subfolder, a malformed release ZIP was installed. With Home Assistant stopped, delete `custom_components/ariston`, install v0.20.8 or later from HACS, and restart.

Releases v0.20.0–v0.20.7 also fail on Home Assistant versions older than 2025.1 because they import an API added in 2025.1. v0.20.8 restores compatibility.

### Temperature values look wrong

If the water heater reports values in the wrong unit, set **Water heater temperature unit override** to `fahrenheit` or `celsius` in the integration options. `auto` uses the unit reported by the device.

### Cannot connect or invalid authentication

- Verify the Ariston NET username and password.
- Check that Home Assistant can reach the Ariston cloud API.
- If the credentials changed, use the re-authentication flow when Home Assistant asks for the password again.
- If the API URL or user agent was customized, restore the defaults and retry.

### Missing entities

Entities are created only when the device reports the corresponding feature. A model without metering, for example, will not create energy sensors. Check **Developer tools → States** and the diagnostics file before reporting a missing entity.

### Enable debug logging

```yaml
logger:
  default: warning
  logs:
    custom_components.ariston: debug
    ariston: debug
```

## Removal

1. Remove the **Ariston NET** entry from **Settings → Devices & services**.
2. Uninstall the integration from HACS, or delete `custom_components/ariston`.
3. Restart Home Assistant.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-test.txt
pytest
```

CI, HACS validation, hassfest and CodeQL run on every push to `main`.

## Contributing

Issues and pull requests are welcome at [richkmeli/ha-ariston](https://github.com/richkmeli/ha-ariston). Include the device model, Home Assistant version and diagnostics when reporting a problem. Remove any personal information before posting logs or diagnostics.

## Credits

- [fustom](https://github.com/fustom) for the upstream [ariston-remotethermo-home-assistant-v3](https://github.com/fustom/ariston-remotethermo-home-assistant-v3) integration.
- [chomupashchuk](https://github.com/chomupashchuk) for the original [v2 integration](https://github.com/chomupashchuk/ariston-remotethermo-home-assistant-v2), which inspired the upstream project.
- All upstream contributors who reverse-engineered and tested the Ariston API.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for the full text.

Ariston, Chaffoteaux and related marks are trademarks of their respective owners.
