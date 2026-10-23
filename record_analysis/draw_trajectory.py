import matplotlib.pyplot as plt
import folium
from recording_format import iter_recording

# Step 1: Read data from the file
file_path = "data/mobili_7.record"  # Replace with your file path

imu_data = []
gps_data = []

for record in iter_recording(file_path):
    if record["type"] == "imu":
        imu_data.append(record)
    elif record["type"] == "gps":
        gps_data.append(record)

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
