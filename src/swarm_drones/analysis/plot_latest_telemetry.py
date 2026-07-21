import argparse
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import yaml


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze the latest waypoint telemetry CSV and generate plots."
    )

    parser.add_argument(
        "--config",
        required=True,
        help="Path to analysis YAML config file.",
    )

    return parser.parse_args()


def load_yaml_config(config_path: str) -> dict[str, Any]:
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError("Config file must contain a YAML dictionary.")

    return config


def get_latest_csv(input_dir: Path, file_pattern: str) -> Path:
    csv_files = sorted(
        input_dir.glob(file_pattern),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not csv_files:
        raise FileNotFoundError(
            f"No telemetry CSV files found in {input_dir} with pattern {file_pattern}"
        )

    return csv_files[0]


def prepare_dataframe(csv_path: Path, time_column: str) -> pd.DataFrame:
    dataframe = pd.read_csv(csv_path)

    if time_column not in dataframe.columns:
        raise ValueError(f"Missing time column: {time_column}")

    dataframe[time_column] = pd.to_datetime(dataframe[time_column])
    dataframe["elapsed_seconds"] = (
        dataframe[time_column] - dataframe[time_column].iloc[0]
    ).dt.total_seconds()

    return dataframe


def save_line_plot(
    dataframe: pd.DataFrame,
    x_column: str,
    y_column: str,
    title: str,
    y_label: str,
    output_file: Path,
) -> None:
    if y_column not in dataframe.columns:
        raise ValueError(f"Missing column for plot: {y_column}")

    plt.figure(figsize=(10, 6))
    plt.plot(dataframe[x_column], dataframe[y_column])
    plt.xlabel("Elapsed Time (seconds)")
    plt.ylabel(y_label)
    plt.title(title)
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(output_file, dpi=300)
    plt.close()


def save_summary(
    dataframe: pd.DataFrame,
    csv_path: Path,
    altitude_column: str,
    distance_column: str,
    output_file: Path,
) -> None:
    max_altitude = dataframe[altitude_column].max()
    min_distance = dataframe[distance_column].min()
    total_rows = len(dataframe)
    duration_seconds = dataframe["elapsed_seconds"].max()

    flight_modes = dataframe["flight_mode"].dropna().unique().tolist()

    summary = f"""
Telemetry Analysis Summary

Input CSV:
{csv_path}

Total telemetry rows:
{total_rows}

Mission duration:
{duration_seconds:.2f} seconds

Maximum mission altitude:
{max_altitude:.2f} meters

Minimum distance to waypoint:
{min_distance:.2f} meters

Observed flight modes:
{flight_modes}

Result:
The telemetry CSV was successfully analyzed. The altitude plot shows the takeoff, flight, and landing behavior. The waypoint distance plot shows how close the drone moved toward the target waypoint.
""".strip()

    output_file.write_text(summary, encoding="utf-8")


def run_analysis(config: dict[str, Any]) -> None:
    input_dir = Path(config["telemetry"]["input_dir"])
    file_pattern = config["telemetry"]["file_pattern"]

    output_dir = Path(config["analysis"]["output_dir"])
    altitude_column = config["analysis"]["altitude_column"]
    distance_column = config["analysis"]["distance_column"]
    time_column = config["analysis"]["time_column"]

    output_dir.mkdir(parents=True, exist_ok=True)

    latest_csv = get_latest_csv(input_dir=input_dir, file_pattern=file_pattern)

    print(f"Latest telemetry CSV found: {latest_csv}")

    dataframe = prepare_dataframe(csv_path=latest_csv, time_column=time_column)

    altitude_plot_file = output_dir / "latest_waypoint_altitude_plot.png"
    distance_plot_file = output_dir / "latest_waypoint_distance_plot.png"
    summary_file = output_dir / "latest_waypoint_summary.txt"

    save_line_plot(
        dataframe=dataframe,
        x_column="elapsed_seconds",
        y_column=altitude_column,
        title="Waypoint Mission Altitude vs Time",
        y_label="Mission Altitude (m)",
        output_file=altitude_plot_file,
    )

    save_line_plot(
        dataframe=dataframe,
        x_column="elapsed_seconds",
        y_column=distance_column,
        title="Distance to Waypoint vs Time",
        y_label="Distance to Waypoint (m)",
        output_file=distance_plot_file,
    )

    save_summary(
        dataframe=dataframe,
        csv_path=latest_csv,
        altitude_column=altitude_column,
        distance_column=distance_column,
        output_file=summary_file,
    )

    print(f"Altitude plot saved: {altitude_plot_file}")
    print(f"Distance plot saved: {distance_plot_file}")
    print(f"Summary saved: {summary_file}")


def main() -> None:
    args = parse_arguments()

    config = load_yaml_config(args.config)
    run_analysis(config)


if __name__ == "__main__":
    main()