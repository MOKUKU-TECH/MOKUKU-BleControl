import matplotlib.pyplot as plt


def read_and_plot_data_subplots(filename):
    """
    Reads data from a file, skipping lines that don't have exactly 7 space-separated values.
    Plots the first 3 data columns in one subplot and the remaining 3 in another.
    """
    time_data = []
    data_columns = [[] for _ in range(6)]  # Prepare lists for the 6 data columns

    try:
        with open(filename, "r") as file:
            for line_num, line in enumerate(file):
                line = line.strip()
                if not line:
                    continue  # Skip empty lines

                parts = line.split()
                if len(parts) != 7:
                    # print(f"Skipping line {line_num + 1}: Incorrect number of elements ({len(parts)}).")
                    continue

                try:
                    # Attempt to convert all parts to float
                    time_value = float(parts[0])
                    values = [float(part) for part in parts[1:]]

                    time_data.append(time_value)
                    for i, value in enumerate(values):
                        data_columns[i].append(value)

                except ValueError:
                    # print(f"Skipping line {line_num + 1}: Non-numeric data found.")
                    continue

    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.")
        return
    except Exception as e:
        print(f"An error occurred while reading the file: {e}")
        return

    if not time_data:
        print("No valid data found to plot.")
        return

    # --- Plotting with Subplots ---
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(10, 10)
    )  # 2 rows, 1 column of subplots

    # Labels for the legend
    labels_first_3 = ["Column 2", "Column 3", "Column 4"]
    labels_last_3 = ["Column 5", "Column 6", "Column 7"]

    # Plot first 3 columns in the first subplot
    for i in range(3):
        ax1.plot(
            time_data,
            data_columns[i],
            marker="o",
            linestyle="-",
            label=labels_first_3[i],
        )
    ax1.set_xlabel("Time (First Column)")
    ax1.set_ylabel("Values")
    ax1.set_title("Data Plot: Columns 2-4")
    ax1.legend()
    ax1.grid(True)

    # Plot remaining 3 columns in the second subplot
    for i in range(3, 6):
        ax2.plot(
            time_data,
            data_columns[i],
            marker="o",
            linestyle="-",
            label=labels_last_3[i - 3],
        )
    ax2.set_xlabel("Time (First Column)")
    ax2.set_ylabel("Values")
    ax2.set_title("Data Plot: Columns 5-7")
    ax2.legend()
    ax2.grid(True)

    plt.tight_layout()  # Adjust spacing between subplots
    plt.show()


# --- Main Execution ---
if __name__ == "__main__":
    # Replace 'your_data_file.txt' with the actual path to your file
    filename = "log.txt"
    read_and_plot_data_subplots(filename)
