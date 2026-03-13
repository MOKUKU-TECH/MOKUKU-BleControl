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
| <video src="https://github.com/user-attachments/assets/f3e1ce54-ce9d-454e-a9f8-6804a5284c24">    | <video src="https://github.com/user-attachments/assets/c99fa5b1-677f-428a-a3d0-675f6aeb1d7c">  |

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
