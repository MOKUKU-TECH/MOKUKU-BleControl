"""Read MOKUKU binary and legacy text recordings."""

import binascii
import mmap
import os
import struct
import warnings


MAGIC = b"MOKUREC\0"
VERSION = 1
SYNC = b"\xa5\x5a"
FRAME_SIZES = {1: 37, 2: 17, 3: 42}


def _binary_records(data, position):
    while (position := data.find(SYNC, position)) >= 0:
        if position + 3 > len(data):
            break
        record_type = data[position + 2]
        size = FRAME_SIZES.get(record_type)
        if size is None or position + size > len(data):
            position += 1
            continue
        crc_position = position + size - 2
        expected_crc = struct.unpack_from("<H", data, crc_position)[0]
        actual_crc = binascii.crc_hqx(data[position + 2:crc_position], 0xffff)
        if actual_crc != expected_crc:
            warnings.warn("Skipping damaged recording frame", RuntimeWarning)
            position += 1
            continue

        if record_type == 1:
            timestamp, ax, ay, az, gx, gy, gz = struct.unpack_from("<q6f", data, position + 3)
            yield {"type": "imu", "time": timestamp, "ax": ax, "ay": ay,
                   "az": az, "gx": gx, "gy": gy, "gz": gz}
        elif record_type == 2:
            timestamp, speed = struct.unpack_from("<qi", data, position + 3)
            yield {"type": "speed", "time": timestamp, "speed": speed}
        else:
            timestamp, age, lat, lng, alt, speed, satellites = struct.unpack_from(
                "<qIddffB", data, position + 3
            )
            yield {"type": "gps", "time": timestamp, "age": age, "lat": lat,
                   "lng": lng, "alt": alt, "speed": speed,
                   "num_satellites": satellites}
        position += size


def _text_records(stream):
    for line in stream:
        parts = line.split()
        if not parts:
            continue
        try:
            if parts[0] == b"imu" and len(parts) == 8:
                timestamp = int(parts[1])
                yield {"type": "imu", "time": timestamp,
                       "ax": float(parts[2]), "ay": float(parts[3]),
                       "az": float(parts[4]), "gx": float(parts[5]),
                       "gy": float(parts[6]), "gz": float(parts[7])}
            elif parts[0] == b"speed" and len(parts) == 3:
                yield {"type": "speed", "time": int(parts[1]), "speed": int(parts[2])}
            elif parts[0] == b"gps" and len(parts) == 8:
                yield {"type": "gps", "time": int(parts[1]), "age": int(parts[2]),
                       "lat": float(parts[3]), "lng": float(parts[4]),
                       "alt": float(parts[5]), "speed": float(parts[6]),
                       "num_satellites": int(parts[7])}
        except ValueError:
            continue


def iter_recording(path):
    with open(path, "rb") as stream:
        if os.fstat(stream.fileno()).st_size == 0:
            return
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            if data[:8] == MAGIC:
                if len(data) < 9 or data[8] != VERSION:
                    raise ValueError("Unsupported recording version")
                yield from _binary_records(data, 9)
                return

            records = _binary_records(data, 0)
            first = next(records, None)
            if first is not None:
                warnings.warn("Recording header is damaged; recovering framed records", RuntimeWarning)
                yield first
                yield from records
                return

        stream.seek(0)
        yield from _text_records(stream)


def read_imu_data(path):
    return [record for record in iter_recording(path) if record["type"] == "imu"]
