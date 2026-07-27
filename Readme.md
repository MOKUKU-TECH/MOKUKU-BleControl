# MOKUKU BLE Communication Protocol

This repository documents the **Bluetooth Low Energy (BLE) protocol** used by
MOKUKU devices, and ships the host-side tools that speak it (a reference control
app and the standalone Vibe Coding Monitor).

The device exposes two BLE characteristics:

| Characteristic   | UUID                                   | Purpose                                 |
| ---------------- | -------------------------------------- | --------------------------------------- |
| Transfer Data    | `beb5483e-36e1-4688-b7f5-ea07361b26a8` | Real-time dashboard data                |
| Transfer Message | `d222e154-1a80-4e71-9a63-2aa2c0ce0a8c` | Configuration / file / command messages |

## Table of Contents

- [Transfer Data](#1-transfer-data)
- [Transfer Message](#2-transfer-message)
- [Download File from MOKUKU](#3-download-file-from-mokuku)
- [Upload File to MOKUKU](#4-upload-file-to-mokuku)
- [DIY Configuration File](#5-diy-configuration-file)
- [Host App & Vibe Coding Monitor Mode](#6-host-app--vibe-coding-monitor-mode)
- [License](#license)

# 1. Transfer Data


**BLE UUID:** `beb5483e-36e1-4688-b7f5-ea07361b26a8`

Used for **real-time dashboard updates**.

## Packet Format (5 bytes)

| Byte | Name  | Description                         |
| ---- | ----- | ----------------------------------- |
| 1    | ID    | Always `1`                          |
| 2    | VEL   | Vehicle speed                       |
| 3    | RPM_A | Engine RPM (high byte or channel A) |
| 4    | RPM_B | Engine RPM (low byte or channel B)  |
| 5    | GAS   | Throttle / gas pedal value          |

## Extended Packet Format (11 bytes)

| Byte | Name        |
| ---- | ----------- |
| 1    | ID (=1)     |
| 2    | VEL         |
| 3    | RPM_A       |
| 4    | RPM_B       |
| 5    | GAS         |
| 6    | TIMESTAMP_1 |
| 7    | TIMESTAMP_2 |
| 8    | TIMESTAMP_3 |
| 9    | TIMESTAMP_4 |
| 10   | BACKLIGHT   |
| 11   | COMMAND     |

### Command List

The `COMMAND` byte above (and the [Direct Command](#direct-command) message)
takes one of:

| Value | Command            |
| ----- | ------------------ |
| 6     | Reboot             |
| 10    | Toggle stereo mode |
| 20    | Keep Idling        |
| 34    | Enable OBD/canbus BLE scan (left eye) |
| 35    | Disable OBD/canbus BLE scan, fall back to GPS mode (left eye) |
| 43    | Left click         |
| 53    | Right click        |
| 66    | Left OTA update    |
| 67    | Right OTA update   |
| 68    | Left MEME update   |
| 69    | Right MEME update  |
| >100  | Set MEME (meme id + 100) |

You can set a meme by sending command (meme id + 100), [the meme list is here](assets/meme_list.txt).

⚠️ **OTA ordering matters**:

1. The system has **two independent chips**, each handling a separate screen:
   * **Left chip** (user's left) is also responsible for **BLE communication**.
   * **Right chip** (user's right) handles display or other processing tasks.
2. **OTA updates must be performed in the correct order:**
   * **First update the Right chip** (command `67`), then the Left chip (command `66`).
   * Reason: the Left chip manages BLE; if updated first, the OTA process may be interrupted by the dropped BLE connection.
3. Recommended precautions before OTA:
   * Ensure both chips have sufficient power.
   * Maintain a stable BLE connection.
   * Avoid interacting with the screens during OTA.

# 2. Transfer Message

**BLE UUID:** `d222e154-1a80-4e71-9a63-2aa2c0ce0a8c`

Used for **configuration, WiFi setup, OTA, file operations, and system commands**.

## WiFi & OTA Firmware URL

The device downloads OTA firmware over WiFi from the configured URL, so set all
three before triggering an OTA update (commands `66`/`67`). Each is a
length-prefixed string message.

### Set WiFi Name

| Byte | Value         |
| ---- | ------------- |
| 1    | `7`           |
| 2    | String length |
| 3..N | WiFi name     |

### Set WiFi Password

| Byte | Value         |
| ---- | ------------- |
| 1    | `8`           |
| 2    | String length |
| 3..N | WiFi password |

### Set OTA Firmware URL

| Byte | Value             |
| ---- | ----------------- |
| 1    | `9`               |
| 2    | String length     |
| 3..N | Firmware base URL |

## Backlight Adjustment

Desired backlight = 100% - offset. If you want 85% backlight, set the offset to 15.

| Byte | Value                 |
| ---- | --------------------- |
| 1    | `5`                   |
| 2    | left backlight offset |

| Byte | Value                  |
| ---- | ---------------------- |
| 1    | `6`                    |
| 2    | right backlight offset |

## Panels choice setup

```
typedef enum {
  PANEL_TYPE_INVALID = 0,
  PANEL_TYPE_VEL = 1,
  PANEL_TYPE_RPM = 2,
  PANEL_TYPE_GRAVITY = 3,
  PANEL_TYPE_PITCHROLL = 4,
  PANEL_TYPE_FUEL = 5,
  PANEL_TYPE_LENGTH = 6,
  PANEL_TYPE_DURATION = 7,
  PANEL_TYPE_TRAJECTORY = 8,
  PANEL_TYPE_TIME = 9,
  PANEL_TYPE_MUSIC = 10,
  PANEL_TYPE_VIBECODING = 11,
} PANEL_TYPE;
```

Panels are a "-"-separated list, e.g. `1-2-3-5` means (vel, rpm, gravity, fuel).
Need a **reboot** to take effect.

| Byte | Value                 |
| ---- | --------------------- |
| 1    | `50`                  |
| 2    | String length         |
| 3..N | left eye panels array |

| Byte | Value                  |
| ---- | ---------------------- |
| 1    | `51`                   |
| 2    | String length          |
| 3..N | right eye panels array |

## VibeCoding Panel Status Text

Sets the text shown on the dedicated VibeCoding panel (`PANEL_TYPE_VIBECODING`,
id `11` - see [Panels choice setup](#panels-choice-setup)), wrapping across up to
~3 lines. Applies immediately, **no reboot needed**. Used by
[Vibe Coding Monitor Mode](#6-host-app--vibe-coding-monitor-mode) to show a live
coding-agent status.

| Byte | Value                   |
| ---- | ----------------------- |
| 1    | `52`                    |
| 2    | String length           |
| 3..N | status text (≤31 bytes) |

`string length = 0` is ignored - this panel has no numeric fallback to revert to.

## Meme Enable/Disable

Controls which meme ids are eligible to display — blocked from both random
selection and motion-triggered playback. Idle (meme id `0`) can never be
disabled; it's silently skipped if included in the list.

### Enable Memes

| Byte | Value | Description |
| ---- | ----- | ----------- |
| 1 | `54` | |
| 2 | count | number of meme ids that follow |
| 3..N | meme id (1 byte each) × count | |

### Disable Memes

| Byte | Value | Description |
| ---- | ----- | ----------- |
| 1 | `55` | |
| 2 | count | number of meme ids that follow |
| 3..N | meme id (1 byte each) × count | |

### Query Meme States

Send `56` with no payload. The device responds with `56`, `count`, then one byte
per installed meme ID (`0` = enabled, `1` = disabled).

## File System Commands

### List Directory

| Byte | Value                 |
| ---- | --------------------- |
| 1    | `60`                  |
| 2    | String length         |
| 3..N | Target directory path |

### SD Card Information

Returns **used space / total space**.

| Byte |
| ---- |
| `61` |

### Delete File

| Byte | Value            |
| ---- | ---------------- |
| 1    | `62`             |
| 2    | String length    |
| 3..N | Target file path |

## Direct Command

Sends a single command byte (see [Command List](#command-list)).

| Byte | Value      |
| ---- | ---------- |
| 1    | `1`        |
| 2    | Command ID |

## Obtain Software Version

| Byte |
| ---- |
| `3`  |

# 3. Download File from MOKUKU

*(txt files only)*

### Step 1 — Open File

Send:

```
id(1 byte)
string_len(1 byte, <255)
string(n bytes)  // file path
```

Device response:

```
id = 65
ret (1 byte)
file_key (4 bytes)
file_size (4 bytes)
```

### Step 2 — Request File Data

Send:

```
id = 66
data_size (1 byte, <255)
file_key (4 bytes)
begin_position (4 bytes)
```

Device response:

```
id = 66
data_size (1 byte)
begin_position (4 bytes)
data (n bytes)
```

# 4. Upload File to MOKUKU

*(txt files only)*

### Step 1 — Open File

Send:

```
id (1 byte)
string_len (1 byte)
string (file path)
```

Device response:

```
id = 63
ret (1 byte)
file_key (4 bytes)
file_size = 0
```

### Step 2 — Send File Data

Send:

```
id = 64
data_size (1 byte)
file_key (4 bytes)
begin_position (4 bytes)
data (n bytes)
```

Special rule:

* Sending **data_size = 0** indicates **end of file**

Device response:

```
id = 64
file_key (4 bytes)
current_position (4 bytes)
```

# 5. DIY Configuration File

Panels can be customized using a configuration file. Example: `assets/config.txt`.

## Panel Types

```
PANEL_TYPE_INVALID = 0
PANEL_TYPE_VEL = 1
PANEL_TYPE_RPM = 2
PANEL_TYPE_GRAVITY = 3
PANEL_TYPE_PITCHROLL = 4
PANEL_TYPE_FUEL = 5
PANEL_TYPE_LENGTH = 6
PANEL_TYPE_DURATION = 7
PANEL_TYPE_TRAJECTORY = 8
PANEL_TYPE_TIME = 9
PANEL_TYPE_MUSIC = 10
```

## Configuration Commands

### Hide Panel

```
i, 45
```

Example: `1, 45`

### Show Panel

```
i, 46
```

Example: `1, 46`

### Clear Panel Elements

```
i, 44
```

Example: `1, 44`

### Set Data Range (Velocity / RPM only)

```
i, 40, min_value, max_value
```

Example: `1, 40, 0, 100`

### Add Text Element

```
i, 41, x, y, font_size, text
```

Example: `1, 41, 0, 61, 60, CPU %`

* `(x, y)` origin is the **center of the panel**

Available font sizes:

```
28, 48, 60, 80, 120, 140, 160
```

# 6. Host App & Vibe Coding Monitor Mode

The **Vibe Coding Monitor** mirrors a Claude Code (or Codex CLI) session's live
status on the left eye's dedicated VibeCoding panel (`PANEL_TYPE_VIBECODING`,
id `11`) — what it's doing right now ("Thinking", "Edit: main.c", "Waiting",
"Idle") — via the [VibeCoding Panel Status Text](#vibecoding-panel-status-text)
command. Full details in
[doc/VIBE_CODING_MONITOR.md](../doc/VIBE_CODING_MONITOR.md) and the
[monitor_app readme](./monitor_app/readme.md#vibe-coding-monitor-mode).

## Quick Start (prebuilt app — no Python needed)

**1. Build & flash the left-eye firmware (one-time, needs ESP-IDF)**

```bash
. $HOME/esp/esp-idf/export.sh
./scripts/build_idf.sh 1
idf.py -B IDF_MOKUKU/build_1 flash monitor
```

**2. Get the host app**

Download the prebuilt app for your OS from **Releases** (or the **Build Vibe
Monitor** GitHub Actions run's artifacts): `MOKUKU-Vibe-Monitor-windows.zip`, or
for Linux one of `-ubuntu20.04.zip` / `-ubuntu22.04.zip` / `-ubuntu24.04.zip`
(pick the newest your system runs; if it reports `GLIBC_… not found`, step down
to an older build). Extract it and double-click **MOKUKU Vibe Monitor** — no
Python, conda, or `pip install` required.

**3. Set it up in the app**

- Click **Scan**, pick your device, click **Connect**.
- Expand **Firmware Update (OTA)** and click **Enable Vibe Coding Monitor Mode**
  (one-time — sets the panel layout, disables OBD/canbus scanning, and reboots
  the device; reconnect after it comes back up).
- Click **Install Claude Code Hooks** (and **Install Codex Hooks** if you use
  Codex, then run `/hooks` inside Codex to trust them).
- Keep the app running while you code.

Once connected, the left eye reflects the session state: `Idle` (no tint),
`Working` (red-orange), `Waiting` (pulsing) — with the tool/file and project
name shown live.

Developers can instead run from source: `pip install -r
monitor_app/requirements.txt` (or the conda env in `ble_ctrl_env.yaml`), then
`python monitor_app/vibe_monitor_app.py`.

## How it works

- The **Enable Vibe Coding Monitor Mode** button sets the left eye to `11-5`
  (VibeCoding + Fuel) and the right eye to `9-7-10` (Time + Duration + Music),
  disables OBD/canbus BLE scanning (command `35`, falls back to GPS mode —
  otherwise the left eye's background OBD-scan role fights whatever's holding the
  phone/host connection), then reboots to apply.
- **Install Claude Code Hooks** merges hook entries into `~/.claude/settings.json`
  (idempotent, backs up the previous file). In the prebuilt bundle the hook
  command points at a bundled console executable (`mokuku-vibe-hook
  --hook-report`, next to the GUI exe — a console binary so the hook can read
  its stdin payload, which the GUI-subsystem exe can't), so
  there's no Python for the end user to have. Each hook event forwards a status
  over a TCP loopback socket (`127.0.0.1:47615`) to the running app — a silent
  no-op if it isn't running.
- The monitor app is a standalone window you start yourself each session (not
  launched by the hooks); it refuses to start a second instance while one is
  already running.

Manual testing without live hooks (the app must already be running):

```bash
cd monitor_app
python3 -m vibe_monitor report working --session test1 --project demo --tool Edit --detail main.c
python3 -m vibe_monitor status
```

## Reference BLE demo app (developers)

`monitor_app/app.py` is a Python demo of the raw protocol — scan for devices,
connect, write data packets, receive notifications, and send commands — built on
[Bleak](https://github.com/hbldh/bleak). **See the detailed doc in the
'monitor_app' subfolder:** [Python BLE Example](./monitor_app/readme.md).

```bash
conda env create -f monitor_app/ble_ctrl_env.yaml
python monitor_app/app.py
```

| [Demo Video](./assets/mokuku_ble_demo_0.mp4)  | [Demo Video Raw](./assets/mokuku_ble_demo_1.mp4)           |
| ------- | -------------------- |
| <video src="https://github.com/user-attachments/assets/7ea8c529-6754-4a41-8ce0-084be0e38f3e">    | <video src="https://github.com/user-attachments/assets/c99fa5b1-677f-428a-a3d0-675f6aeb1d7c">  |

# License

Licensed under the MIT License.
