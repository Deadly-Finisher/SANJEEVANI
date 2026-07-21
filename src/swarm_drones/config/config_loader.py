from pathlib import Path
from typing import Any

import yaml


class ConfigLoader:
    """
    Loads project configuration from YAML files.

    The loader first reads a master config index file.
    The index file contains paths to all other config files.

    This avoids scattering config file paths across the codebase.
    """

    def __init__(self, config_index_path: str) -> None:
        self.config_index_path = Path(config_index_path)

    def load_yaml(self, file_path: Path) -> dict[str, Any]:
        """
        Load a single YAML file and return its content as a dictionary.
        """

        if not file_path.exists():
            raise FileNotFoundError(f"Config file not found: {file_path}")

        with file_path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)

        if data is None:
            return {}

        if not isinstance(data, dict):
            raise ValueError(f"Config file must contain a YAML dictionary: {file_path}")

        return data

    def load_all(self) -> dict[str, Any]:
        """
        Load all configuration files listed in the master config index.
        """

        config_index = self.load_yaml(self.config_index_path)

        if "config_files" not in config_index:
            raise KeyError("Missing 'config_files' section in config index.")

        combined_config: dict[str, Any] = {
            "config_index": config_index
        }

        for config_name, config_path in config_index["config_files"].items():
            loaded_config = self.load_yaml(Path(config_path))
            combined_config[config_name] = loaded_config

        return combined_config
