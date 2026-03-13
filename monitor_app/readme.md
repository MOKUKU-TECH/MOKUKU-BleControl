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
