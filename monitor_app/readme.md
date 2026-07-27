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

## Meme Test Panel

Connect over BLE, then click **Open Meme Test Panel**. It loads the current state
of each installed meme, groups them by app tag, and provides per-meme and per-tag
enable toggles. The **不可编辑** tag is read-only.

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

Reflects a Claude Code and/or Codex CLI session's live status ("Thinking",
"Edit: main.c", "Waiting", "Idle") on a dedicated VibeCoding panel
(`PANEL_TYPE_VIBECODING`, id `11`), via BLE command `52`
([VibeCoding Panel Status Text](../Readme.md#vibecoding-panel-status-text)).
Requires the firmware in this repo's parent project (`IDF_MOKUKU`) to be built
with the VibeCoding panel — see
[../../doc/VIBE_CODING_MONITOR.md](../../doc/VIBE_CODING_MONITOR.md) if you have
that repo checked out.

### Quick start (prebuilt app — no Python needed)

1. Download the zip for your OS from the repo's **Releases** (or the
   **Build Vibe Monitor** GitHub Actions run's artifacts):
   `MOKUKU-Vibe-Monitor-windows.zip`, or for Linux one of
   `-ubuntu20.04.zip` (glibc 2.31+, oldest systems), `-ubuntu22.04.zip`
   (glibc 2.35+), or `-ubuntu24.04.zip` (glibc 2.39+). Pick the newest one
   your system runs; if it reports `GLIBC_… not found`, step down to an older
   build.
2. Extract it anywhere and double-click **MOKUKU Vibe Monitor** inside the
   extracted folder. No Python, conda, or `pip install` required.
3. Pick a transport tab and connect: **Bluetooth** → **Scan** → pick device →
   **Connect**, or **Serial Port** → **Refresh Ports** → pick the **right eye's**
   USB port → **Connect** (no BLE pairing needed, and it survives the vibe-mode
   reboot). Both use the identical message protocol.
4. Expand **Firmware Update (OTA)** and click **Enable Vibe Coding Monitor
   Mode** (one-time — reboots the device; reconnect after it comes back up).
5. Click **Install Claude Code Hooks** (and **Install Codex Hooks** if you use
   Codex — then run `/hooks` inside Codex to trust them).

That's it. Keep the app running while you code; it forwards each session's
status to MOKUKU. The rest of this section explains each piece and the
run-from-source path for developers.

### 1. Enable the mode on the device

Connect over BLE, then expand the **Firmware Update (OTA)** panel and click
**"Enable Vibe Coding Monitor Mode"**.
This sends the panel layout (left: `11-5` — VibeCoding + Fuel, right: `9-7-10`
— Time + Duration + Music), disables OBD/canbus BLE scanning (command `35`,
falls back to GPS mode), and reboots the device to apply it. One-time setup;
reconnect after the device comes back up. (The reference `app.py` has the same
button — the folded-in copy here means end users never need `app.py` or conda.)

Disabling OBD scanning avoids a real failure mode: the left eye's BLE *client*
role (which normally scans for an OBD/ELM327 device) and its BLE *server* role
(the phone/host connection) share one radio, and toggling between them on every
connect/disconnect can produce a connect → disconnect → reconnect loop that
fights whatever's trying to hold the host connection — a phone, `app.py`, or
`vibe_monitor_app.py` below.

### 2. Wire up Claude Code hooks

Easiest: click **"Install Claude Code Hooks"** in the app (a one-time step;
same idempotent merge into the global `~/.claude/settings.json`). The prebuilt
app wires the hook command to a bundled console executable — the hook runs
`mokuku-vibe-hook --hook-report` (a console binary beside the GUI exe, so it can
read the JSON payload Claude Code pipes in on stdin), so there's no Python for
you to have installed.

From source, use the CLI instead:

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
`PreCompact` hook event forwards the status (over a TCP loopback socket,
`127.0.0.1:47615`) to the running app - if it isn't running, this is a silent
no-op.

### 2b. Optional: also wire up Codex CLI hooks

```bash
python3 install_codex_hooks.py            # merges into ~/.codex/hooks.json
python3 install_codex_hooks.py --project  # or into ./.codex/hooks.json for just this project
```

Same idempotent merge/backup/`--dry-run`/`--remove` as `install_hooks.py`,
or click **"Install Codex Hooks"** in `vibe_monitor_app.py`. `report_status.py`
handles both agents - Codex's own hook system is a close port of Claude
Code's, invoked here with `--agent codex --event <Name>` baked into the
command rather than trusted from Codex's own payload.

**Codex additionally requires manual trust**: after installing, run `/hooks`
inside the Codex CLI to review and approve these entries - unlike Claude
Code, they don't take effect just by being written to the config file. This
is a newer, still-evolving Codex feature; if nothing shows up, check
`/hooks` first and compare against
[developers.openai.com/codex/hooks](https://developers.openai.com/codex/hooks).

| hook event | status shown |
|---|---|
| `SessionStart`, `Stop`, `SessionEnd` | `Idle` |
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStop`, `PreCompact` | tool name (+ detail), or `Working` |
| `Notification` (`permission_prompt` only) | `Waiting` |
| `MessageDisplay` | `Thinking` (throttled to ~once/2.5s per session - clears a stale `Waiting` once Claude resumes after you answer a question/permission prompt, since no other hook fires for that) |

`Notification` also fires for other sub-types - most commonly `idle_prompt`,
after *every* turn simply because Claude finished and is waiting for your
next message, no action needed from you. `install_hooks.py` installs it
scoped to `"matcher": "permission_prompt"` so only a real blocking wait
shows `Waiting` - otherwise it'd flip to `Waiting` after every single
response, which looks like a bug.

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

Either way, it's a small standalone dark-themed window (separate from
`app.py`, styling in `theme.py`) with a
**Bluetooth / Serial Port** tab at the top. Bluetooth: **Scan**, pick your
device, **Connect**. Serial Port: **Refresh Ports**, pick the **right eye's**
USB port, **Connect** — the message protocol is identical, and serial skips BLE
pairing and survives the vibe-mode reboot (only the left eye reboots). It shows
the connection state, the current Claude Code status, a scrolling activity log,
and an **"Install Claude Code Hooks"** button (step 2 above, if you skipped the
CLI). Unlike
the old headless daemon this replaces, nothing scans or connects
automatically - you always know whether it's actually connected. It's not
launched by the hooks either; run it yourself each session, and it refuses
to start a second instance while one is already running (same socket).

Connect and Disconnect both back up bleak's own D-Bus calls with a
`bluetoothctl connect`/`disconnect` subprocess call, since bleak's calls can
silently hang or fail on Linux/BlueZ. This matters most on disconnect - if
the radio-level link stays up while the app thinks it's disconnected, MOKUKU
never resumes advertising and won't show up in the next scan. Scanning uses
`async with BleakScanner()` so an interrupted scan can't leave the adapter
stuck and blocking future scans, and scan failures are logged rather than
leaving the UI stuck on "Scanning...".

The device side had a matching firmware bug: `ObdBleClientSetup()`
(`IDF_SHARED/backend/BleClient.cpp`) called `BLEDevice::init()` again on
every phone disconnect, which corrupted the already-running BLE stack and
left MOKUKU permanently unable to advertise after the first disconnect -
fixed by only calling it once, on the initial boot setup. `onDisconnect`
also now directly calls `BLEDevice::startAdvertising()` itself instead of
relying on it as an incidental side effect of that same
`ObdBleClientSetup()`/`CreateBleService()` chain (which exists for an
unrelated reason - restarting the OBD BLE *client* scan). The VibeCoding
panel also now shows `Not Connected` as soon as the phone disconnects,
instead of freezing on the last status it received.

That covers a clean disconnect, but a crashed or suspended app can leave
the BLE link nominally "up" for a while with no disconnect event at all -
as a backstop, this app's every-2s time-sync write doubles as a heartbeat
the panel expects to keep hearing; after 8s of silence it falls back to
`Not Connected` on its own regardless of what BLE itself reports.

### Firmware update (OTA)

Click **Firmware Update (OTA)** to expand a panel (hidden by default) with the
same OTA controls as the reference `app.py`, so the packaged app can update
firmware too. It also holds the **Enable Vibe Coding Monitor Mode** button
(step 1 above):

- **Set WiFi** — sends the network name/password the device downloads the
  firmware over (string messages `7`/`8`).
- **Set URL** — the firmware `.bin` URL (string message `9`); prefilled with a
  default build URL you can overwrite.
- **Start OTA** — triggers the **right eye first** (command `67`), then after
  ~0.5s the **left eye** (command `66`). The left/INS eye owns the BLE link, so
  updating it first can interrupt the right eye's update - hence right-before-left
  (matching the ordering note under [OTA Update Commands](#ota-update-commands)).
  The left-eye trigger drops the connection as it reboots into the update.

Set WiFi and the URL once (they persist on the device), keep the device
powered, and don't disconnect until it finishes.

### Manual testing (app must already be running)

```bash
python3 -m vibe_monitor report working --session test1 --project demo --tool Edit --detail main.c
python3 -m vibe_monitor report working --session test2 --project demo --tool shell --agent codex
python3 -m vibe_monitor status   # tracked sessions (tagged by agent), connected MOKUKU device, current state/text
```

Set `MOKUKU_VIBE_MONITOR_DRY_RUN=1` when invoking `vibe_monitor/report_status.py`
directly to print what would be sent instead of actually sending it.
