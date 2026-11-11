# MOKUKU II Monitor

Desktop and command-line clients for MOKUKU II (one ESP32-S31). MOKUKU II speaks a new
protocol, so it needs this app instead of `monitor_app`:

- one Transfer Message characteristic (`d222e154-…`) carries every message and its replies;
- byte 0 is the message type: `1` data, `2` set, `3` get;
- set and get name a property, and replies carry a result code.

The protocol reference is `doc/MOKUKU_II_BLE_CONTROL.md` in the MobiliMOKUKU repository;
`protocol.py` mirrors it.

| File | Contents |
|---|---|
| `protocol.py` | Message types, properties, results, encoders and decoders |
| `ble_client.py` | Bleak client: scan for `mokukuii*`, connect, one request at a time |
| `app.py` | PyQt5 window, styled with `monitor_app/theme.py` |
| `cli.py` | Command-line client |

## Setup

Uses the same environment as `monitor_app` (Bleak and PyQt5):

```
conda env create -f monitor_app/ble_ctrl_env.yaml
conda activate ble_ctrl
```

## Desktop app

```
python monitor_app_II/app.py
```

Scan, pick a `mokukuii*` device, and connect. The app then reads the MOKUKU version, MAC address,
SD card space, wake word model, command language, and settings. Settings (Wi-Fi name and password, remote address, OBD scanning)
each have **Get** and **Set**. Under Panels, pick each eye's 5 data panels in next-page order
(memes are always shown as well); **Get** reads them (also on connecting) and **Set** applies
them to both eyes. **Left Next** and **Right Next** move one eye to its next panel (from memes,
both eyes return to their data panels), and **Data / Meme** switches both eyes between modes. **Send** writes one dashboard data packet; **Reboot** sends the
reboot command; **Firmware…** opens the firmware update window: pick the app image
(`IDF_MOKUKU_II_prototype.bin` from `IDF_MOKUKU_II_prototype/output/`) and **Update** sends it with a
progress bar, after which the device restarts into it; **Cancel** (or closing the window) stops it, and
the device restarts into its old firmware; **Rollback…** restarts the device into the firmware in its
other slot if it is older, and **Switch Slot…** whatever its age. The window lists each slot's
version and build time, and which runs and boots next; **Refresh** reads them again. Under Recordings, **List** reads the names in `/sdcard/record`, **Download**
saves the selected recording (a window shows its progress and rate; **Cancel** stops it, keeping
the bytes received; saving over that file again offers to resume), and **Delete All** deletes every recording after a confirmation.

## Command line

```
python monitor_app_II/cli.py scan
python monitor_app_II/cli.py get version mac_address sd_card wake_word_model multinet_language
python monitor_app_II/cli.py set wifi_name Home
python monitor_app_II/cli.py set obd_enabled off
python monitor_app_II/cli.py get panels
python monitor_app_II/cli.py set panels speed,rpm,gravity,pitch_roll,clock fuel,trip_distance,driving_time,route,music
python monitor_app_II/cli.py set panel_action next_left   # next_right, toggle_mode
python monitor_app_II/cli.py data 60 2400 75 --command none
python monitor_app_II/cli.py ls                      # /sdcard/record by default
python monitor_app_II/cli.py download /sdcard/record/mobili_1.record --output mobili_1.record
python monitor_app_II/cli.py download /sdcard/record/mobili_1.record --output mobili_1.record --resume
python monitor_app_II/cli.py upload firmware.bin /sdcard/firmware.bin   # replaces an existing file
python monitor_app_II/cli.py delete-recordings --yes
python monitor_app_II/cli.py update IDF_MOKUKU_II_prototype.bin   # the app image from output/
python monitor_app_II/cli.py get firmware_slots   # each OTA slot's version and build time
python monitor_app_II/cli.py rollback --yes      # the other slot's firmware, only if it is older
python monitor_app_II/cli.py switch-slot --yes   # the other slot's firmware, older or not
```

Without `--address`, the CLI connects to the strongest `mokukuii*` device.

`update` sends the firmware like an upload; the device writes it to its other slot and restarts
into it, or after a failure (including Ctrl-C) restarts into the old firmware.

Ctrl-C stops a transfer on the device as well. An interrupted download keeps the bytes received;
`--resume` continues after them once the device confirms by CRC that they match its file.

While connected, the client asks for the version whenever it has sent nothing for 10 s: MOKUKU II
disconnects a host silent for 30 s, so a host lost without a clean disconnect does not block
advertising.

A reply too long for one notification (long strings at the default MTU) is read from the
characteristic instead; the client does this after a 3 s timeout.
