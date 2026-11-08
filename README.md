# Calyps'HOME - Home Assistant Integration (Cloud)

🇬🇧 **English** | 🇫🇷 [Français](README.fr.md)

[![Validation](https://github.com/Legobis965/hass-calypshome-cloud/actions/workflows/validate.yml/badge.svg)](https://github.com/Legobis965/hass-calypshome-cloud/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.11%2B-41BDF5.svg)](https://www.home-assistant.io/)

Custom integration to control your Calyps'HOME roller shutters and read your sensors (temperature, illuminance) from Home Assistant through the Calyps'HOME cloud.

## ⚠️ Disclaimer

**This custom component is independent and is in no way affiliated with the Calyps'HOME brand.**

- ✋ **Unofficial project**: this component was developed independently and is not supported by the manufacturer Calyps'HOME
- 🚫 **No warranty**: this software is provided "as is", without any guarantee that it works
- ⚠️ **Use at your own risk**: the author cannot be held liable for any malfunction, hardware damage or data loss resulting from the use of this component
- 🔧 **Limited support**: support is provided on a voluntary basis, with no commitment
- 📝 **MIT license**: this project is released under the MIT license, see the [LICENSE](LICENSE) file

**By using this component, you accept these terms.**

## Project history

This repository is a fork of the original project [saniho/calypshome](https://github.com/saniho/calypshome).

The original project worked **locally only**: it talked directly to the Calyps'HOME box on the local network.

This fork was rewritten to work **entirely through the cloud**: the integration talks to the Avidsen cloud API (`calypshome.avidsen.one`) just like the official mobile app does. It therefore works from anywhere, without depending on the local network.

Thanks to the original author for the groundwork and the initial ideas.

## Features

- ✅ Automatic discovery of all roller shutters
- ✅ Automatic discovery of sensors (temperature and illuminance)
- ✅ Open / Close / Stop
- ✅ Precise positioning (0-100 %), carried out by the shutter motor
- ✅ **Real** position reported by the cloud (no timer-based estimation)
- ✅ Real-time updates over WebSocket (shutters, temperature, illuminance)
- ✅ **Favorite position** button for shutters that support it
- ✅ Objects **hidden** in the Calyps'HOME app are not imported
- ✅ Translated entity names (English / French), grouped by device
- ✅ Set up from the user interface, with duplicate account detection
- ✅ Re-authentication and change of email or password without removing the integration
- ✅ Entities become unavailable when the cloud does not respond, with automatic retry at startup
- ✅ Works from any network (cloud)

## Screenshots

> Screenshots taken in Home Assistant 2026.11 (French interface) with sample data.

**Adding the integration**: only the email and password of the Calyps'HOME app are required.

<p align="center">
  <img src="images/config-flow.png" width="80%" alt="Calyps'HOME setup form">
</p>

**Discovered devices**: one device per shutter and per sensor.

<p align="center">
  <img src="images/integration-devices.png" width="80%" alt="List of the integration's devices">
</p>

**Shutter device page**: open / stop / close controls and favorite position button.

<p align="center">
  <img src="images/device-shutter.png" width="80%" alt="Shutter device page with the Favorite position button">
</p>

**Real shutter position**: position slider driven by the level reported by the cloud.

<p align="center">
  <img src="images/cover-more-info.png" width="80%" alt="Dialog of a shutter open at 45 %">
</p>

**Sensor device page**: temperature and illuminance.

<p align="center">
  <img src="images/device-sensor.png" width="80%" alt="Sensor device page with temperature and illuminance">
</p>

## Requirements

- Home Assistant **2024.11** or later (the integration logo is displayed from **2026.3** onwards)
- A Calyps'HOME account (the credentials of the mobile app)

## Installation

### Option 1: HACS (recommended)

1. In HACS, open the ⋮ menu → **Custom repositories**
2. Add `https://github.com/Legobis965/hass-calypshome-cloud` with the type **Integration**
3. Search for **Calyps'HOME Cloud** in HACS and download it
4. Restart Home Assistant
5. Go to **Settings** → **Devices & services** → **+ Add integration**
6. Search for **Calyps'HOME Cloud**
7. Enter the email and password of your Calyps'HOME account

### Option 2: manual installation

1. Copy the `custom_components/calypshome_cloud` folder into the `config/custom_components/` folder of Home Assistant
2. Restart Home Assistant
3. Go to **Settings** → **Devices & services** → **+ Add integration**
4. Search for **Calyps'HOME Cloud**
5. Enter the email and password of your Calyps'HOME account

### Upgrading from an earlier version

Update from HACS, then restart Home Assistant. Your entities keep their identifier (`entity_id`): existing automations, scripts and dashboards keep working. Starting with version 1.2.0, Home Assistant 2024.11 or later is required.

## Configuration

After installation, your roller shutters and sensors are discovered automatically: one device is created for each of them, with its entities (`cover`, `button`, `sensor`, see [Entities](#entities)).

### Changing the email or password

- **Password changed or rejected**: Home Assistant shows a *"Re-authentication required"* notification. Click it and enter the new password, or another email if the account changed.
- **At any time**: **Settings** → **Devices & services** → **Calyps'HOME Cloud** → ⋮ menu of the entry → **Reconfigure**.

In both cases, entities and their history are kept. An email already used by another entry is rejected.

## Entities

Names are built from the device name and translated according to the Home Assistant language (English examples below).

| Entity | Type | Created for | Description |
|---|---|---|---|
| `<shutter>` | `cover` | every shutter | State (open, closed, opening, closing) and position 0-100 % |
| `<shutter> Favorite position` | `button` | every shutter supporting the `FAV_CALL_1` action | Sends the shutter to the favorite position stored in its motor |
| `<sensor> Temperature` | `sensor` | every sensor with a temperature reading | Temperature in °C |
| `<sensor> Illuminance` | `sensor` | every sensor with an illuminance reading | Illuminance in lx |

Objects hidden in the Calyps'HOME app are not imported.

## Usage

### In dashboards

Shutters are shown with the standard Home Assistant controls: open, stop, close and position slider. Favorite position buttons and sensors can be added from each device page (**Add to dashboard**).

### In automations

```yaml
# Close all shutters at sunset
automation:
  - alias: "Close shutters at sunset"
    triggers:
      - trigger: sun
        event: sunset
    actions:
      - action: cover.close_cover
        target:
          entity_id: all
```

```yaml
# Send the living room shutter to its favorite position when it is hot outside
automation:
  - alias: "Living room shutter to favorite position when hot"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.terrace_sensor_temperature
        above: 28
    actions:
      - action: button.press
        target:
          entity_id: button.living_room_favorite_position
```

### In scripts

```yaml
# Open the kitchen shutter halfway
script:
  kitchen_half_open:
    sequence:
      - action: cover.set_cover_position
        target:
          entity_id: cover.kitchen
        data:
          position: 50
```

### Available actions

```yaml
# Open a shutter (replace with your shutter's entity ID)
action: cover.open_cover
target:
  entity_id: cover.your_shutter

# Close a shutter
action: cover.close_cover
target:
  entity_id: cover.your_shutter

# Precise position (0 = closed, 100 = open)
action: cover.set_cover_position
target:
  entity_id: cover.your_shutter
data:
  position: 75

# Stop a moving shutter
action: cover.stop_cover
target:
  entity_id: cover.your_shutter

# Send a shutter to its favorite position
action: button.press
target:
  entity_id: button.your_shutter_favorite_position
```

> Entity IDs depend on your device names and on the Home Assistant language when they were created: check them in **Settings** → **Devices & services** → **Entities**.

## Troubleshooting

### Shutters are not discovered

1. Check your cloud login credentials
2. Check the logs: **Settings** → **System** → **Logs**, then search for `calypshome_cloud`
3. Check that your Calyps'HOME account actually contains shutters
4. Check that the shutter is not **hidden** in the Calyps'HOME app: hidden objects are ignored

### Entities are "unavailable"

The Calyps'HOME cloud is not responding. The integration retries automatically every 5 minutes; entities become available again as soon as the cloud responds.

### A shutter stays "opening" or "closing"

Without a new position for 90 seconds, the movement is considered finished. If your shutters take longer, increase `MOTION_TIMEOUT` in `cover.py`.

### The "Favorite position" button does not appear

It is only created for shutters for which the cloud reports the `FAV_CALL_1` action. Check that a favorite position is stored for this shutter in the Calyps'HOME app.

### Commands do not work

1. Check that commands work from the Calyps'HOME app
2. Check the Home Assistant logs
3. Make sure your cloud account is valid

### Debug logs

The easiest way: **Settings** → **Devices & services** → **Calyps'HOME Cloud** → **Enable debug logging**, reproduce the problem, then disable it to download the log file.

You can also add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.calypshome_cloud: debug
```

## Removal

1. **Settings** → **Devices & services** → **Calyps'HOME Cloud** → ⋮ menu of the entry → **Delete**
2. If the integration was installed with HACS, remove it from HACS as well
3. Restart Home Assistant

## Development

This component was developed by analyzing the HTTP traffic of the official Calyps'HOME mobile app, in order to faithfully reproduce its calls to the Avidsen cloud API.

### Continuous integration

On every push and every week, GitHub Actions validates the integration with:
- **hassfest**: official Home Assistant validation (manifest, translations, config flow);
- **HACS**: repository validation for HACS.

### Publishing a release

1. Update `version` in `custom_components/calypshome_cloud/manifest.json` (e.g. `1.2.0`).
2. Create and push the matching tag:
   ```bash
   git tag 1.2.0
   git push origin 1.2.0
   ```
3. The **Release** workflow checks that the tag matches the manifest, then publishes the GitHub release with generated notes and the `calypshome_cloud.zip` archive.

## About this project

This component is an **unofficial community project** created to integrate Calyps'HOME roller shutters into Home Assistant through the cloud.

**Relationship with the brand**:
- ❌ Not developed by Calyps'HOME
- ❌ Not endorsed by Calyps'HOME
- ❌ Not officially supported by Calyps'HOME
- ✅ Developed by the community, for the community

**Credits**:
- Original project (local mode): [saniho/calypshome](https://github.com/saniho/calypshome)
- This fork: complete rewrite in cloud mode

**Responsibilities**:
- The author of this component is not responsible for malfunctions of your installation
- Calyps'HOME is not responsible for problems related to the use of this component
- Any change to your account configuration is made under your own responsibility

## License

MIT License: this software is provided without any warranty. See [LICENSE](LICENSE).

## Support

For any question or problem:
- 📖 Read this documentation first
- 🔍 Check the [existing issues](https://github.com/Legobis965/hass-calypshome-cloud/issues)
- 💬 Open a new issue if needed

**Note**: for hardware problems or issues with the Calyps'HOME service itself, contact the official Calyps'HOME support directly.
