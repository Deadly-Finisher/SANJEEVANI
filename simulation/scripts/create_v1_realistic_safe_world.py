from pathlib import Path
import random
import math
import re


PROJECT_ROOT = Path.home() / "Programs" / "SWARM_DRONES"
PX4_ROOT = Path.home() / "Programs" / "PX4" / "PX4-Autopilot"

WORLD_DIR = PROJECT_ROOT / "simulation" / "worlds"
MODEL_DIR = PROJECT_ROOT / "simulation" / "models"

SOURCE_WORLD = WORLD_DIR / "battlefield_sar_world_v1.sdf"
OUTPUT_WORLD = WORLD_DIR / "battlefield_sar_world_v1_realistic.sdf"
PX4_OUTPUT_WORLD = PX4_ROOT / "Tools" / "simulation" / "gz" / "worlds" / "battlefield_sar_world_v1_realistic.sdf"


def write_model_config(model_dir: Path, name: str):
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.config").write_text(
        f"""<?xml version="1.0"?>
<model>
  <name>{name}</name>
  <version>1.0</version>
  <sdf version="1.9">model.sdf</sdf>
  <author>
    <name>SWARM_DRONES</name>
  </author>
  <description>Stable low-poly realistic tree for V1 world.</description>
</model>
"""
    )


def create_simple_pine_model() -> Path:
    model_dir = MODEL_DIR / "trees" / "stable_realistic_pine"
    write_model_config(model_dir, "stable_realistic_pine")

    model_sdf = model_dir / "model.sdf"

    model_sdf.write_text(
        """<?xml version="1.0"?>
<sdf version="1.9">
  <model name="stable_realistic_pine">
    <static>true</static>
    <link name="tree_link">

      <visual name="trunk">
        <pose>0 0 0.8 0 0 0</pose>
        <geometry>
          <cylinder>
            <radius>0.12</radius>
            <length>1.6</length>
          </cylinder>
        </geometry>
        <material>
          <ambient>0.28 0.16 0.07 1</ambient>
          <diffuse>0.28 0.16 0.07 1</diffuse>
        </material>
      </visual>

      <visual name="lower_foliage">
        <pose>0 0 1.8 0 0 0</pose>
        <geometry>
          <cone>
            <radius>0.95</radius>
            <length>1.6</length>
          </cone>
        </geometry>
        <material>
          <ambient>0.03 0.22 0.05 1</ambient>
          <diffuse>0.04 0.36 0.07 1</diffuse>
        </material>
      </visual>

      <visual name="upper_foliage">
        <pose>0 0 2.7 0 0 0</pose>
        <geometry>
          <cone>
            <radius>0.65</radius>
            <length>1.3</length>
          </cone>
        </geometry>
        <material>
          <ambient>0.03 0.25 0.05 1</ambient>
          <diffuse>0.04 0.40 0.07 1</diffuse>
        </material>
      </visual>

      <collision name="trunk_collision">
        <pose>0 0 0.8 0 0 0</pose>
        <geometry>
          <cylinder>
            <radius>0.16</radius>
            <length>1.6</length>
          </cylinder>
        </geometry>
      </collision>

    </link>
  </model>
</sdf>
"""
    )

    return model_sdf


def create_simple_broadleaf_model() -> Path:
    model_dir = MODEL_DIR / "trees" / "stable_realistic_broadleaf"
    write_model_config(model_dir, "stable_realistic_broadleaf")

    model_sdf = model_dir / "model.sdf"

    model_sdf.write_text(
        """<?xml version="1.0"?>
<sdf version="1.9">
  <model name="stable_realistic_broadleaf">
    <static>true</static>
    <link name="tree_link">

      <visual name="trunk">
        <pose>0 0 0.8 0 0 0</pose>
        <geometry>
          <cylinder>
            <radius>0.14</radius>
            <length>1.6</length>
          </cylinder>
        </geometry>
        <material>
          <ambient>0.30 0.18 0.08 1</ambient>
          <diffuse>0.30 0.18 0.08 1</diffuse>
        </material>
      </visual>

      <visual name="canopy_main">
        <pose>0 0 2.05 0.15 0.05 0</pose>
        <geometry>
          <box>
            <size>1.7 1.3 1.2</size>
          </box>
        </geometry>
        <material>
          <ambient>0.04 0.26 0.06 1</ambient>
          <diffuse>0.05 0.42 0.08 1</diffuse>
        </material>
      </visual>

      <visual name="canopy_side">
        <pose>0.35 0.2 2.35 0.05 0.2 0.4</pose>
        <geometry>
          <box>
            <size>1.2 1.1 0.9</size>
          </box>
        </geometry>
        <material>
          <ambient>0.05 0.30 0.07 1</ambient>
          <diffuse>0.06 0.45 0.10 1</diffuse>
        </material>
      </visual>

      <collision name="trunk_collision">
        <pose>0 0 0.8 0 0 0</pose>
        <geometry>
          <cylinder>
            <radius>0.18</radius>
            <length>1.6</length>
          </cylinder>
        </geometry>
      </collision>

    </link>
  </model>
</sdf>
"""
    )

    return model_sdf


def make_include(name: str, model_path: Path, x: float, y: float, yaw: float) -> str:
    return f"""
    <include>
      <name>{name}</name>
      <uri>file://{model_path}</uri>
      <pose>{x:.2f} {y:.2f} 0.00 0 0 {yaw:.3f}</pose>
    </include>
"""


def make_zone_marker(name: str, x: float, y: float, sx: float, sy: float, r: float, g: float, b: float) -> str:
    return f"""
    <model name="{name}">
      <static>true</static>
      <pose>{x:.2f} {y:.2f} 0.012 0 0 0</pose>
      <link name="link">
        <visual name="zone_visual">
          <geometry>
            <box>
              <size>{sx:.2f} {sy:.2f} 0.02</size>
            </box>
          </geometry>
          <material>
            <ambient>{r:.2f} {g:.2f} {b:.2f} 0.65</ambient>
            <diffuse>{r:.2f} {g:.2f} {b:.2f} 0.65</diffuse>
          </material>
        </visual>
      </link>
    </model>
"""


def main():
    if not SOURCE_WORLD.exists():
        raise FileNotFoundError(f"Source V1 world not found: {SOURCE_WORLD}")

    pine_model = create_simple_pine_model()
    broadleaf_model = create_simple_broadleaf_model()

    world = SOURCE_WORLD.read_text()

    world = world.replace('name="battlefield_sar_world_v1"', 'name="battlefield_sar_world_v1_realistic"')
    world = world.replace("name='battlefield_sar_world_v1'", "name='battlefield_sar_world_v1_realistic'")

    # Remove old round field_tree includes only in the copied world.
    world = re.sub(
        r"\s*<include>\s*<name>field_tree_.*?</include>",
        "",
        world,
        flags=re.DOTALL,
    )

    world = re.sub(
        r"\s*<include>.*?field_tree.*?</include>",
        "",
        world,
        flags=re.DOTALL,
    )

    random.seed(11)

    additions = []

    # Keep tree count modest for stability.
    tree_positions = [
        (-28, -22), (-34, -15), (-30, -4), (-35, 8), (-28, 20),
        (30, -25), (35, -15), (32, -5), (36, 12), (28, 24),
        (-18, -32), (-8, -30), (12, -31), (22, -33),
        (-24, 28), (-12, 31), (8, 30), (22, 28),
    ]

    for idx, (x, y) in enumerate(tree_positions, start=1):
        yaw = random.uniform(-math.pi, math.pi)
        model = pine_model if idx % 2 == 0 else broadleaf_model
        additions.append(make_include(f"stable_realistic_tree_{idx:02d}", model, x, y, yaw))

    # Very low flat zone markers, not large poles/balloons.
    additions.append(make_zone_marker("zone_marker_takeoff_landing", 0, -35, 12, 8, 0.10, 0.35, 0.10))
    additions.append(make_zone_marker("zone_marker_person_zone", 5, -10, 14, 10, 0.25, 0.25, 0.10))
    additions.append(make_zone_marker("zone_marker_person_vehicle_zone", 18, -12, 16, 10, 0.25, 0.20, 0.10))
    additions.append(make_zone_marker("zone_marker_structure_debris_zone", -18, 18, 16, 12, 0.20, 0.18, 0.15))
    additions.append(make_zone_marker("zone_marker_central_review_zone", 0, 0, 12, 12, 0.15, 0.15, 0.15))

    insert_text = "\n".join(additions)

    world = world.replace("</world>", insert_text + "\n  </world>", 1)

    OUTPUT_WORLD.write_text(world)

    PX4_OUTPUT_WORLD.parent.mkdir(parents=True, exist_ok=True)
    PX4_OUTPUT_WORLD.write_text(world)

    print("Created safe realistic V1 world:")
    print(OUTPUT_WORLD)
    print("Copied to PX4:")
    print(PX4_OUTPUT_WORLD)
    print("Original battlefield_sar_world_v1.sdf was NOT modified.")


if __name__ == "__main__":
    main()
