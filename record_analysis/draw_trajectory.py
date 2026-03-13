import matplotlib.pyplot as plt
import folium

# Step 1: Read data from the file
file_path = "data/mobili_7.record"  # Replace with your file path

imu_data = []
gps_data = []

with open(file_path, "r") as file:
    for line in file:
        parts = line.strip().split()
        if parts[0] == "imu":
            imu_data.append(
                {
                    "time": int(parts[1]),
                    "ax": float(parts[2]),
                    "ay": float(parts[3]),
                    "az": float(parts[4]),
                    "gx": float(parts[5]),
                    "gy": float(parts[6]),
                    "gz": float(parts[7]),
                }
            )
        elif parts[0] == "gps":
            gps_data.append(
                {
                    "time": int(parts[1]),
                    "lat": float(parts[2]),
                    "lng": float(parts[3]),
                    "alt": float(parts[4]),
                    "speed": float(parts[5]),
                    "num_satellites": int(parts[6]),
                }
            )

# Print parsed data for verification
print("IMU Data:", len(imu_data))
print("GPS Data:", len(gps_data))

# Extract GPS coordinates
gps_times = [entry["time"] for entry in gps_data]
gps_lats = [entry["lat"] for entry in gps_data]
gps_lngs = [entry["lng"] for entry in gps_data]

# Step 3: Plot the GPS trajectory
# plt.figure(figsize=(10, 6))
# plt.plot(gps_lngs, gps_lats, marker='o', linestyle='-', color='b')
# plt.title('GPS Trajectory')
# plt.xlabel('Longitude')
# plt.ylabel('Latitude')
# plt.grid(True)
# plt.show()

# Step 4: Overlay GPS trajectory on a GIS map using Folium
map_center = [gps_lats[0], gps_lngs[0]]  # Use the first GPS point as the map center
mymap = folium.Map(location=map_center, zoom_start=17)

# Add GPS points and lines to the map
for i in range(len(gps_lats) - 1):
    folium.PolyLine(
        [[gps_lats[i], gps_lngs[i]], [gps_lats[i + 1], gps_lngs[i + 1]]], color="blue"
    ).add_to(mymap)

# Save the map as an HTML file
mymap.save(file_path + ".html")
print("Map saved as " + file_path + ".html")
