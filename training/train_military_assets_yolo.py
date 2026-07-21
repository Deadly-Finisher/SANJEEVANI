from pathlib import Path
import shutil

import yaml
from ultralytics import YOLO


def load_config(path: str) -> dict:
    with open(path, "r") as file:
        return yaml.safe_load(file)


def resolve_device(device_value: str):
    if device_value != "auto":
        return device_value

    try:
        import torch
        if torch.cuda.is_available():
            return 0
    except Exception:
        pass

    return "cpu"


def main() -> None:
    config = load_config("configs/training/military_assets_yolo_finetune.yaml")

    dataset_yaml_path = Path(config["dataset"]["yaml_path"])
    base_model = config["model"]["base_model"]

    epochs = int(config["training"]["epochs"])
    image_size = int(config["training"]["image_size"])
    batch_size = int(config["training"]["batch_size"])
    workers = int(config["training"]["workers"])
    device = resolve_device(config["training"]["device"])
    project = config["training"]["project"]
    run_name = config["training"]["run_name"]
    patience = int(config["training"]["patience"])

    model_dir = Path(config["output"]["model_dir"])
    best_model_name = config["output"]["best_model_name"]
    last_model_name = config["output"]["last_model_name"]

    if not dataset_yaml_path.exists():
        raise FileNotFoundError(f"Dataset YAML not found: {dataset_yaml_path}")

    print("Using dataset YAML:", dataset_yaml_path)
    print("Labels will be read from your YAML and will NOT be changed.")
    print("Base model:", base_model)
    print("Device:", device)

    dataset_config = yaml.safe_load(dataset_yaml_path.read_text())
    print("\nLabels being used:")
    for class_id, class_name in dataset_config["names"].items():
        print(f"{class_id}: {class_name}")

    model = YOLO(base_model)

    model.train(
        data=str(dataset_yaml_path),
        epochs=epochs,
        imgsz=image_size,
        batch=batch_size,
        workers=workers,
        device=device,
        project=project,
        name=run_name,
        patience=patience,
        exist_ok=True,
    )

    run_dir = Path(project) / run_name
    weights_dir = run_dir / "weights"

    best_pt = weights_dir / "best.pt"
    last_pt = weights_dir / "last.pt"

    model_dir.mkdir(parents=True, exist_ok=True)

    if best_pt.exists():
        shutil.copy2(best_pt, model_dir / best_model_name)
        print("Best model saved to:", model_dir / best_model_name)

    if last_pt.exists():
        shutil.copy2(last_pt, model_dir / last_model_name)
        print("Last model saved to:", model_dir / last_model_name)

    print("\nFine-tuning completed.")


if __name__ == "__main__":
    main()
