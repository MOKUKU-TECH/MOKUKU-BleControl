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
each have **Get** and **Set**. **Send** writes one dashboard data packet; **Reboot** sends the
reboot command. Under Recordings, **List** reads the names in `/sdcard/record`, **Download**
saves the selected recording (a window shows its progress and rate; **Cancel** stops it, keeping
the bytes received; saving over that file again offers to resume), and **Delete All** deletes every recording after a confirmation.

## Command line

```
python monitor_app_II/cli.py scan
python monitor_app_II/cli.py get version mac_address sd_card wake_word_model multinet_language
python monitor_app_II/cli.py set wifi_name Home
python monitor_app_II/cli.py set obd_enabled off
python monitor_app_II/cli.py data 60 2400 75 --command none
python monitor_app_II/cli.py ls                      # /sdcard/record by default
python monitor_app_II/cli.py download /sdcard/record/mobili_1.record --output mobili_1.record
python monitor_app_II/cli.py download /sdcard/record/mobili_1.record --output mobili_1.record --resume
python monitor_app_II/cli.py upload firmware.bin /sdcard/firmware.bin   # replaces an existing file
python monitor_app_II/cli.py delete-recordings --yes
```

Without `--address`, the CLI connects to the strongest `mokukuii*` device.

Ctrl-C stops a transfer on the device as well. An interrupted download keeps the bytes received;
`--resume` continues after them once the device confirms by CRC that they match its file.

While connected, the client asks for the version whenever it has sent nothing for 10 s: MOKUKU II
disconnects a host silent for 30 s, so a host lost without a clean disconnect does not block
advertising.

A reply too long for one notification (long strings at the default MTU) is read from the
characteristic instead; the client does this after a 3 s timeout.
