from pathlib import Path
from datetime import datetime
import csv

import cv2
from ultralytics import YOLO


INPUT_DIR = Path("outputs/camera_frames")
OUTPUT_DIR = Path("outputs/yolo_saved_frames")
CSV_PATH = OUTPUT_DIR / "detections.csv"

MODEL_NAME = "yolo11n.pt"
CONF_THRESHOLD = 0.30


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    image_paths = sorted(
        list(INPUT_DIR.glob("*.jpg"))
        + list(INPUT_DIR.glob("*.png"))
        + list(INPUT_DIR.glob("*.jpeg"))
    )

    if not image_paths:
        raise FileNotFoundError(f"No images found in {INPUT_DIR.resolve()}")

    print(f"Loading YOLO model: {MODEL_NAME}")
    model = YOLO(MODEL_NAME)

    rows = []

    for image_path in image_paths:
        frame = cv2.imread(str(image_path))

        if frame is None:
            print(f"Skipping unreadable image: {image_path}")
            continue

        results = model(frame, conf=CONF_THRESHOLD, verbose=False)
        result = results[0]

        annotated = result.plot()

        output_path = OUTPUT_DIR / f"detected_{image_path.name}"
        cv2.imwrite(str(output_path), annotated)

        if result.boxes is not None:
            for box in result.boxes:
                cls_id = int(box.cls[0])
                cls_name = model.names[cls_id]
                conf = float(box.conf[0])

                x1, y1, x2, y2 = box.xyxy[0].tolist()

                rows.append({
                    "timestamp": datetime.now().isoformat(),
                    "image_name": image_path.name,
                    "class_id": cls_id,
                    "class_name": cls_name,
                    "confidence": round(conf, 4),
                    "x1": round(x1, 2),
                    "y1": round(y1, 2),
                    "x2": round(x2, 2),
                    "y2": round(y2, 2),
                    "output_image": str(output_path),
                })

        print(f"Processed: {image_path.name} -> {output_path.name}")

    with open(CSV_PATH, "w", newline="") as csvfile:
        fieldnames = [
            "timestamp",
            "image_name",
            "class_id",
            "class_name",
            "confidence",
            "x1",
            "y1",
            "x2",
            "y2",
            "output_image",
        ]

        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print("\nYOLO saved-frame testing completed.")
    print(f"Annotated frames saved to: {OUTPUT_DIR.resolve()}")
    print(f"Detection CSV saved to: {CSV_PATH.resolve()}")
    print(f"Total detections: {len(rows)}")


if __name__ == "__main__":
    main()