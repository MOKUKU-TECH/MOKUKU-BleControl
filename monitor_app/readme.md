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
