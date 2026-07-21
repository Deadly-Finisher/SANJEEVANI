import argparse
from pprint import pprint

from swarm_drones.config.config_loader import ConfigLoader


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SWARM DRONES project entry point."
    )

    parser.add_argument(
        "--config-index",
        required=True,
        help="Path to the master config index YAML file."
    )

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    config_loader = ConfigLoader(config_index_path=args.config_index)
    config = config_loader.load_all()

    print("Configuration loaded successfully.")
    print("Loaded config sections:")
    pprint(list(config.keys()))


if __name__ == "__main__":
    main()
