# MOKUKU BLE Communication Protocol

This repository documents the **Bluetooth Low Energy (BLE) protocol** used by MOKUKU devices.

The protocol defines two BLE characteristics:

| Characteristic   | UUID                                   | Purpose                                 |
| ---------------- | -------------------------------------- | --------------------------------------- |
| Transfer Data    | `beb5483e-36e1-4688-b7f5-ea07361b26a8` | Real-time dashboard data                |
| Transfer Message | `d222e154-1a80-4e71-9a63-2aa2c0ce0a8c` | Configuration / file / command messages |

## Table of Contents

- [Transfer Data](#1-transfer-data)
- [Transfer Message](#2-transfer-message)
- [Download File from MOKUKU](#3-download-file-from-mokuku)
- [Upload File to MOKUKU](#4-upload-file-to-mokuku)
- [Demo](#6-demo) : **see more detailed doc in 'monitor_app' subfolder.** [Python BLE Example](./monitor_app/readme.md)
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


## Extended Packet Format (10 bytes)

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

| Value | Command            |
| ----- | ------------------ |
| 10    | Toggle stereo mode |
| 43    | Left click         |
| 53    | Right click        |
| 66    | Left OTA update    |
| 67    | Right OTA update   |

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


# 2. Transfer Message

**BLE UUID:** `d222e154-1a80-4e71-9a63-2aa2c0ce0a8c`

Used for **configuration, WiFi setup, file operations, and system commands**.


## WiFi Configuration

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

Panels can be customized using a configuration file.

Example: `assets/config.txt`


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

Example

```
1, 45
```

### Show Panel

```
i, 46
```

Example

```
1, 46
```

### Clear Panel Elements

```
i, 44
```

Example

```
1, 44
```

### Set Data Range (Velocity / RPM only)

```
i, 40, min_value, max_value
```

Example

```
1, 40, 0, 100
```


### Add Text Element

```
i, 41, x, y, font_size, text
```

Example

```
1, 41, 0, 61, 60, CPU %
```

* `(x, y)` origin is **center of the panel**

Available font sizes:

```
28, 48, 60, 80, 120, 140, 160
```

# 6. Demo

This example demonstrates how to connect to a MOKUKU device over Bluetooth Low Energy (BLE) and communicate using the MOKUKU protocol.
The example shows how to:

* scan for BLE devices
* connect to a MOKUKU device
* write data packets
* receive notifications
* send protocol commands

The implementation is written in Python using Bleak, a cross-platform BLE library.
**See more detailed doc in 'monitor_app' subfolder.** [Python BLE Example](./monitor_app/readme.md)

## Create conda environment

```
conda env create -f monitor_app/ble_ctrl_env.yaml
```

## Run the demo app

```
python monitor_app/app.py
```

| [Demo Video](./assets/mokuku_ble_demo_0.mp4)  | [Demo Video Raw](./assets/mokuku_ble_demo_1.mp4)           |
| ------- | -------------------- |
| <video src="https://github.com/user-attachments/assets/7ea8c529-6754-4a41-8ce0-084be0e38f3e">    | <video src="https://github.com/user-attachments/assets/c99fa5b1-677f-428a-a3d0-675f6aeb1d7c">  |


# License

Licensed under the MIT License.
