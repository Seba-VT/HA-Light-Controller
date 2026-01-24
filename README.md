# SVT Light Controller (Home Assistant Add-on)

A Home Assistant add-on that runs the SVT Light Controller service with a built-in web UI. It uses MQTT and Home Assistant entities to coordinate circadian lighting, sleep/wakeup modes, and weather-based color temperature adjustments across groups of lights.

## Features
- Web UI with ingress (no separate web server needed)
- Create multiple controllers with unique inputs (lights)
- Circadian brightness and color temperature curves (editable)
- Master settings that controllers can inherit
- Sleep / WakeUp mode overrides
- Weather-based color temperature adjustment
- Automatic cleanup of retained MQTT topics for removed controllers

## Installation
1. Copy this folder to your HA host at:
   `/addons/local/svt_light_controller`
2. In Home Assistant:
   - **Settings → Add-ons → Add-on Store**
   - Open the three-dot menu → **Repositories**
   - Enable local add-ons if needed
3. Find **SVT Light Controller** in the **Local add-ons** section and click **Install**.

## Configuration
Configure the add-on options in the UI:
- `mqtt_host` (default: `core-mosquitto`)
- `mqtt_port` (default: `1883`)
- `mqtt_username` / `mqtt_password` (optional)
- `log_level` (`trace|debug|info|warning|error`)
- `circadian_interval` (seconds between circadian updates)
- `wakeup_interval` (seconds between wakeup updates)

## Dependencies
- **MQTT broker** (required): the add-on publishes and subscribes to MQTT topics (e.g., Mosquitto).  
  Default host: `core-mosquitto` on port `1883`.

## Usage
1. Open the add-on UI (Ingress panel).
2. Click **Add Controller**.
3. In **Inputs**, double‑click lights to add/remove them (buttons are hidden).
4. Configure circadian curves, limits, and modes as desired.
5. Click **Save**.

### Notes
- Lights that are already used by another controller appear disabled in the Available list.
- Hovering a disabled light shows which controller is using it.
- The Available badge shows `usable/total` counts.

## Troubleshooting
- If you delete a controller and still see old MQTT activity, the add-on clears retained topics automatically on startup and when retained data arrives.
- If the UI looks stale, hard‑refresh the browser or clear cache.

## Files
- `svt_light_controller/` – add‑on source and web UI
- `custom_components/svt_light_controller/` – HA integration (if used)

---

If you want this README tailored for HACS, GitHub, or a public release, tell me the target format.
