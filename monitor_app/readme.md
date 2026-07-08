# Python BLE Client Example


This example demonstrates how to connect to a MOKUKU device over Bluetooth Low Energy (BLE) and communicate using the MOKUKU protocol.
The example shows how to:

* scan for BLE devices
* connect to a MOKUKU device
* write data packets
* receive notifications
* send protocol commands

The implementation is written in Python using Bleak, a cross-platform BLE library.


## Create conda environment

```
conda env create -f monitor_app/ble_ctrl_env.yaml
```

## Run the demo app

```
python monitor_app/app.py
```

| [Demo Video](../assets/mokuku_ble_demo_0.mp4)  | [Demo Video Raw](../assets/mokuku_ble_demo_1.mp4)           |
| ------- | -------------------- |
| <video src="https://github.com/user-attachments/assets/7ea8c529-6754-4a41-8ce0-084be0e38f3e">    | <video src="https://github.com/user-attachments/assets/c99fa5b1-677f-428a-a3d0-675f6aeb1d7c">  |

### OTA Update Commands

| Command | Description          |
| ------- | -------------------- |
| 66      | **Left OTA update**  |
| 67      | **Right OTA update** |

⚠️ **Important Notice**:

1. The system has **two independent chips**, each handling a separate screen:
   * **Left chip** (user’s left) is also responsible for **BLE communication**.
   * **Right chip** (user’s right) handles display or other processing tasks.
2. **OTA updates must be performed in the correct order:**
   * **First update the Right chip**, then update the Left chip.
   * Reason: The Left chip manages BLE; if updated first, the OTA process may be interrupted or fail due to loss of BLE connectivity.
3. Recommended precautions before OTA:
   * Ensure both chips have sufficient power.
   * Maintain a stable BLE connection.
   * Avoid interacting with the screens during OTA.


## Set MOKUKU as CPU/GPU usage monitor

Follow these steps to display **CPU and GPU usage** on your MOKUKU device:

✅ **Tips:** Make sure BLE connection is stable during upload.

### 1️⃣ Enable Realtime Data

In `app.py`, set:

```python id="enable_realtime"
send_realtime_data = True
```

* **CPU usage** will be displayed on the **Velocity Panel**.
* **GPU usage** will be displayed on the **GPU Panel**.

### 2️⃣ Upload Example Configuration

(All the parameter are setup, you can directly click the button)

1. Open `assets/config.txt` (or the path set in `ble_client.py` as `CONFIG_FILE_PATH`).
2. Click the **Upload File** button to send it to MOKUKU.

Example `config.txt` content:

```text id="config_example"
# Panel 1 (CPU)
1, 44                # Clear all existing elements
1, 40, 0, 100        # Set value range: 0–100
1, 41, 0, 61, 60, CPU %  # Add CPU text element

# Panel 2 (GPU)
2, 44                # Clear all existing elements
2, 40, 0, 100        # Set value range: 0–100
2, 41, 0, -72, 48, gpu % # Add GPU text element
```

### 3️⃣ Reboot MOKUKU

| Step | Video          |
| ------- | -------------------- |
| Disconnect and reconnect power to **reboot the device**.<br>Reconnect via BLE; MOKUKU will now display **your PC CPU and GPU data**.      | <video src="https://github.com/user-attachments/assets/a0e28482-c74e-4fdc-8506-c81567d8ea54">  |

### 4️⃣ Recover MOKUKU (Reset Configuration)

* To reset or recover MOKUKU, send an **empty `config.txt`** file.
* This clears all custom panels and restores the default display.

## Vibe Coding Monitor Mode

Reflects a Claude Code session's live status ("Thinking", "Edit: main.c",
"Waiting", "Idle") on a dedicated VibeCoding panel (`PANEL_TYPE_VIBECODING`, id
`11`), via BLE command `52`
([VibeCoding Panel Status Text](../Readme.md#vibecoding-panel-status-text)).
Requires the firmware in this repo's parent project (`IDF_MOKUKU`) to be built
with the VibeCoding panel — see
[../../doc/VIBE_CODING_MONITOR.md](../../doc/VIBE_CODING_MONITOR.md) if you have
that repo checked out.

### 1. Enable the mode on the device

In `app.py`, click **"Enable Vibe Coding Monitor Mode"**. This sends the panel
layout (left: `11-5` — VibeCoding + Fuel, right: `9-7-10` — Time + Duration +
Music), disables OBD/canbus BLE scanning (command `35`, falls back to GPS mode),
and reboots the device to apply it. One-time setup; reconnect after the device
comes back up.

Disabling OBD scanning avoids a real failure mode: the left eye's BLE *client*
role (which normally scans for an OBD/ELM327 device) and its BLE *server* role
(the phone/host connection) share one radio, and toggling between them on every
connect/disconnect can produce a connect → disconnect → reconnect loop that
fights whatever's trying to hold the host connection — a phone, `app.py`, or
`vibe_monitor_app.py` below.

### 2. Wire up Claude Code hooks

```bash
python3 install_hooks.py            # merges into ~/.claude/settings.json
python3 install_hooks.py --project  # or into ./.claude/settings.json for just this project
python3 install_hooks.py --dry-run  # preview the result first without writing anything
```

Idempotent and safe to re-run — only adds entries, existing hooks (including ones
for unrelated projects/devices) are left untouched, and the previous settings file
is backed up to `settings.json.bak`. Undo with `python3 install_hooks.py --remove`.

Once installed, every `SessionStart` / `UserPromptSubmit` / `PreToolUse` /
`PostToolUse` / `Notification` / `Stop` / `SubagentStop` / `SessionEnd` /
`PreCompact` hook event calls `vibe_monitor/report_status.py`, which forwards
the status over a local socket to `vibe_monitor_app.py` (see below) - if
that app isn't running, this is a silent no-op.

| hook event | status shown |
|---|---|
| `SessionStart`, `Stop`, `SessionEnd` | `Idle` |
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStop`, `PreCompact` | tool name (+ detail), or `Working` |
| `Notification` | `Waiting` |

### 3. Run the monitor app and connect

```bash
python vibe_monitor_app.py
```

Or make it a clickable app (one-time setup):

```bash
python3 install_desktop_launcher.py            # installs to your app menu + Desktop
python3 install_desktop_launcher.py --dry-run  # preview the .desktop file first
python3 install_desktop_launcher.py --remove   # uninstall
```

Searchable in your app menu as "MOKUKU Vibe Monitor" afterward. First
double-click on a new Desktop icon may prompt "Untrusted Application
Launcher" in some file managers - click through it once.

Either way, it's a small standalone window (separate from `app.py`): click
**Scan**, pick your device, click **Connect**. It shows the device connection
state, the current Claude Code status, and a scrolling activity log. Unlike
the old headless daemon this replaces, nothing scans or connects
automatically - you always know whether it's actually connected. It's not
launched by the hooks either; run it yourself each session, and it refuses
to start a second instance while one is already running (same socket).

### Manual testing (app must already be running)

```bash
python3 -m vibe_monitor report working --session test1 --project demo --tool Edit --detail main.c
python3 -m vibe_monitor status   # tracked sessions, connected MOKUKU device, current state/text
```

Set `MOKUKU_VIBE_MONITOR_DRY_RUN=1` when invoking `vibe_monitor/report_status.py`
directly to print what would be sent instead of actually sending it.
