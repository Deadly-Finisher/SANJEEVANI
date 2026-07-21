from pathlib import Path
import math
import random
import re


PROJECT_ROOT = Path.home() / "Programs" / "SWARM_DRONES"
WORLD_DIR = PROJECT_ROOT / "simulation" / "worlds"
MODEL_DIR = PROJECT_ROOT / "simulation" / "models"

V1_WORLD = WORLD_DIR / "battlefield_sar_world_v1.sdf"
V2_WORLD = WORLD_DIR / "battlefield_sar_world_v2.sdf"

PX4_WORLD_DIR = Path.home() / "Programs" / "PX4" / "PX4-Autopilot" / "Tools" / "simulation" / "gz" / "worlds"


def write_model_config(model_path: Path, name: str):
    model_path.mkdir(parents=True, exist_ok=True)
    (model_path / "model.config").write_text(
        f"""<?xml version="1.0"?>
<model>
  <name>{name}</name>
  <version>1.0</version>
  <sdf version="1.9">model.sdf</sdf>
  <author>
    <name>SWARM_DRONES</name>
    <email>local@simulation</email>
  </author>
  <description>Procedural realistic low-poly model for UAV simulation.</description>
</model>
"""
    )


def create_pine_mesh(mesh_path: Path):
    mesh_path.parent.mkdir(parents=True, exist_ok=True)

    vertices = []
    faces = []

    def add_cone(z_base, radius, height, segments=10):
        start = len(vertices) + 1
        apex = (0.0, 0.0, z_base + height)
        vertices.append(apex)

        for i in range(segments):
            angle = 2 * math.pi * i / segments
            # Slight irregularity so it does not look like a perfect cone
            r = radius * (0.85 + 0.25 * ((i % 3) / 2))
            vertices.append((r * math.cos(angle), r * math.sin(angle), z_base))

        for i in range(segments):
            a = start
            b = start + 1 + i
            c = start + 1 + ((i + 1) % segments)
            faces.append((a, b, c))

    add_cone(1.2, 1.1, 1.5)
    add_cone(2.1, 0.9, 1.35)
    add_cone(3.0, 0.65, 1.15)

    with open(mesh_path, "w") as file:
        file.write("# Low-poly pine foliage mesh\n")
        for v in vertices:
            file.write(f"v {v[0]} {v[1]} {v[2]}\n")
        for f in faces:
            file.write(f"f {f[0]} {f[1]} {f[2]}\n")


def create_broadleaf_mesh(mesh_path: Path):
    mesh_path.parent.mkdir(parents=True, exist_ok=True)
    random.seed(7)

    vertices = []
    faces = []

    rings = [
        (1.2, 0.25),
        (1.5, 0.65),
        (1.8, 0.95),
        (2.1, 0.85),
        (2.4, 0.55),
        (2.7, 0.20),
    ]

    segments = 12

    for z, radius in rings:
        for i in range(segments):
            angle = 2 * math.pi * i / segments
            irregular = 0.75 + random.random() * 0.45
            rx = radius * irregular * 1.15
            ry = radius * irregular * 0.85
            vertices.append((rx * math.cos(angle), ry * math.sin(angle), z))

    for r in range(len(rings) - 1):
        for i in range(segments):
            a = r * segments + i + 1
            b = r * segments + ((i + 1) % segments) + 1
            c = (r + 1) * segments + ((i + 1) % segments) + 1
            d = (r + 1) * segments + i + 1
            faces.append((a, b, c))
            faces.append((a, c, d))

    with open(mesh_path, "w") as file:
        file.write("# Irregular broadleaf canopy mesh\n")
        for v in vertices:
            file.write(f"v {v[0]} {v[1]} {v[2]}\n")
        for f in faces:
            file.write(f"f {f[0]} {f[1]} {f[2]}\n")


def create_realistic_tree_models():
    pine_dir = MODEL_DIR / "trees" / "realistic_pine"
    broadleaf_dir = MODEL_DIR / "trees" / "realistic_broadleaf"

    write_model_config(pine_dir, "realistic_pine")
    write_model_config(broadleaf_dir, "realistic_broadleaf")

    pine_mesh = pine_dir / "meshes" / "pine_foliage.obj"
    broadleaf_mesh = broadleaf_dir / "meshes" / "broadleaf_canopy.obj"

    create_pine_mesh(pine_mesh)
    create_broadleaf_mesh(broadleaf_mesh)

    pine_sdf = f"""<?xml version="1.0"?>
<sdf version="1.9">
  <model name="realistic_pine">
    <static>true</static>
    <link name="tree_link">
      <visual name="trunk_visual">
        <pose>0 0 0.65 0 0 0</pose>
        <geometry>
          <cylinder>
            <radius>0.12</radius>
            <length>1.3</length>
          </cylinder>
        </geometry>
        <material>
          <ambient>0.30 0.18 0.08 1</ambient>
          <diffuse>0.30 0.18 0.08 1</diffuse>
        </material>
      </visual>

      <visual name="foliage_visual">
        <geometry>
          <mesh>
            <uri>file://{pine_mesh}</uri>
          </mesh>
        </geometry>
        <material>
          <ambient>0.04 0.25 0.06 1</ambient>
          <diffuse>0.04 0.35 0.08 1</diffuse>
        </material>
      </visual>

      <collision name="trunk_collision">
        <pose>0 0 0.65 0 0 0</pose>
        <geometry>
          <cylinder>
            <radius>0.15</radius>
            <length>1.3</length>
          </cylinder>
        </geometry>
      </collision>
    </link>
  </model>
</sdf>
"""

    broadleaf_sdf = f"""<?xml version="1.0"?>
<sdf version="1.9">
  <model name="realistic_broadleaf">
    <static>true</static>
    <link name="tree_link">
      <visual name="trunk_visual">
        <pose>0 0 0.75 0 0 0</pose>
        <geometry>
          <cylinder>
            <radius>0.16</radius>
            <length>1.5</length>
          </cylinder>
        </geometry>
        <material>
          <ambient>0.32 0.20 0.10 1</ambient>
          <diffuse>0.32 0.20 0.10 1</diffuse>
        </material>
      </visual>

      <visual name="canopy_visual">
        <geometry>
          <mesh>
            <uri>file://{broadleaf_mesh}</uri>
          </mesh>
        </geometry>
        <material>
          <ambient>0.05 0.30 0.08 1</ambient>
          <diffuse>0.06 0.42 0.10 1</diffuse>
        </material>
      </visual>

      <collision name="trunk_collision">
        <pose>0 0 0.75 0 0 0</pose>
        <geometry>
          <cylinder>
            <radius>0.18</radius>
            <length>1.5</length>
          </cylinder>
        </geometry>
      </collision>
    </link>
  </model>
</sdf>
"""

    (pine_dir / "model.sdf").write_text(pine_sdf)
    (broadleaf_dir / "model.sdf").write_text(broadleaf_sdf)

    return pine_dir / "model.sdf", broadleaf_dir / "model.sdf"


def make_include(name: str, uri: Path, x: float, y: float, z: float, yaw: float = 0.0):
    return f"""
    <include>
      <name>{name}</name>
      <uri>file://{uri}</uri>
      <pose>{x:.2f} {y:.2f} {z:.2f} 0 0 {yaw:.3f}</pose>
    </include>
"""


def make_box_model(name, x, y, z, sx, sy, sz, r, g, b, yaw=0.0):
    return f"""
    <model name="{name}">
      <static>true</static>
      <pose>{x:.2f} {y:.2f} {z:.2f} 0 0 {yaw:.3f}</pose>
      <link name="link">
        <visual name="visual">
          <geometry>
            <box>
              <size>{sx:.2f} {sy:.2f} {sz:.2f}</size>
            </box>
          </geometry>
          <material>
            <ambient>{r:.2f} {g:.2f} {b:.2f} 1</ambient>
            <diffuse>{r:.2f} {g:.2f} {b:.2f} 1</diffuse>
          </material>
        </visual>
        <collision name="collision">
          <geometry>
            <box>
              <size>{sx:.2f} {sy:.2f} {sz:.2f}</size>
            </box>
          </geometry>
        </collision>
      </link>
    </model>
"""


def create_realistic_world_v2(pine_sdf: Path, broadleaf_sdf: Path):
    if not V1_WORLD.exists():
        raise FileNotFoundError(f"V1 world not found: {V1_WORLD}")

    world = V1_WORLD.read_text()

    world = world.replace('name="battlefield_sar_world_v1"', 'name="battlefield_sar_world_v2"')
    world = world.replace("name='battlefield_sar_world_v1'", "name='battlefield_sar_world_v2'")

    # Remove old round/spherical tree includes from V2 only
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

    random.seed(21)

    additions = []

    # Larger terrain visual
    additions.append(
        make_box_model(
            "large_realistic_terrain_v2",
            0, 0, -0.04,
            420, 420, 0.04,
            0.24, 0.30, 0.18,
            0,
        )
    )

    # Roads
    additions.append(make_box_model("north_south_asphalt_road_v2", 0, 0, 0.015, 7, 360, 0.03, 0.04, 0.04, 0.04, 0))
    additions.append(make_box_model("east_west_asphalt_road_v2", 0, 0, 0.018, 360, 7, 0.03, 0.04, 0.04, 0.04, 0))
    additions.append(make_box_model("diagonal_dirt_track_v2", -55, 42, 0.02, 95, 4.5, 0.03, 0.25, 0.20, 0.13, 0.55))

    # Zone floor patches
    additions.append(make_box_model("person_vehicle_zone_ground_v2", 45, -35, 0.01, 45, 38, 0.02, 0.18, 0.22, 0.16, 0))
    additions.append(make_box_model("fire_smoke_zone_ground_v2", -45, 38, 0.01, 42, 36, 0.02, 0.23, 0.18, 0.14, 0))
    additions.append(make_box_model("debris_structure_zone_ground_v2", 55, 45, 0.01, 48, 42, 0.02, 0.20, 0.20, 0.18, 0))
    additions.append(make_box_model("landing_return_zone_ground_v2", 0, -60, 0.012, 28, 28, 0.02, 0.12, 0.22, 0.12, 0))

    # Add forest belts and realistic trees
    tree_count = 0

    tree_positions = []

    # Western forest strip
    for _ in range(35):
        tree_positions.append((random.uniform(-95, -65), random.uniform(-90, 90)))

    # Eastern forest strip
    for _ in range(35):
        tree_positions.append((random.uniform(65, 100), random.uniform(-95, 95)))

    # Scattered trees away from roads
    for _ in range(45):
        x = random.uniform(-90, 90)
        y = random.uniform(-90, 90)
        if abs(x) < 8 or abs(y) < 8:
            continue
        tree_positions.append((x, y))

    for x, y in tree_positions:
        tree_count += 1
        yaw = random.uniform(-3.14, 3.14)
        if tree_count % 2 == 0:
            additions.append(make_include(f"realistic_pine_{tree_count:03d}", pine_sdf, x, y, 0, yaw))
        else:
            additions.append(make_include(f"realistic_broadleaf_{tree_count:03d}", broadleaf_sdf, x, y, 0, yaw))

    # Add some extra simple buildings to make world larger
    building_model = MODEL_DIR / "buildings" / "field_building" / "model.sdf"
    damaged_model = MODEL_DIR / "buildings" / "damaged_building" / "model.sdf"
    vehicle_model = MODEL_DIR / "vehicles" / "recon_vehicle" / "model.sdf"
    person_model = MODEL_DIR / "humans" / "field_person" / "model.sdf"
    smoke_model = MODEL_DIR / "effects" / "smoke_fire_effect" / "model.sdf"
    debris_model = MODEL_DIR / "barriers" / "debris_pile" / "model.sdf"

    if building_model.exists():
        additions.append(make_include("v2_field_building_01", building_model, 55, 48, 0, 0.2))
        additions.append(make_include("v2_field_building_02", building_model, 74, 42, 0, -0.3))
        additions.append(make_include("v2_field_building_03", building_model, -42, -48, 0, 0.1))

    if damaged_model.exists():
        additions.append(make_include("v2_damaged_building_01", damaged_model, 42, 62, 0, -0.4))
        additions.append(make_include("v2_damaged_building_02", damaged_model, -58, 42, 0, 0.5))

    if vehicle_model.exists():
        additions.append(make_include("v2_vehicle_01", vehicle_model, 36, -32, 0, 0.2))
        additions.append(make_include("v2_vehicle_02", vehicle_model, 51, -28, 0, -0.5))
        additions.append(make_include("v2_vehicle_03", vehicle_model, -15, 12, 0, 1.5))

    if person_model.exists():
        for i, (x, y) in enumerate([(38, -38), (42, -32), (50, -42), (18, -18), (-22, 24), (62, 50)], start=1):
            additions.append(make_include(f"v2_person_{i:02d}", person_model, x, y, 0, random.uniform(-3.14, 3.14)))

    if smoke_model.exists():
        additions.append(make_include("v2_smoke_fire_01", smoke_model, -48, 40, 0, 0))
        additions.append(make_include("v2_smoke_fire_02", smoke_model, -58, 50, 0, 0))

    if debris_model.exists():
        for i, (x, y) in enumerate([(54, 52), (60, 46), (48, 40), (-45, 35), (-52, 44)], start=1):
            additions.append(make_include(f"v2_debris_{i:02d}", debris_model, x, y, 0, random.uniform(-1, 1)))

    insert_text = "\n".join(additions)

    world = world.replace("</world>", insert_text + "\n  </world>", 1)

    V2_WORLD.write_text(world)

    PX4_WORLD_DIR.mkdir(parents=True, exist_ok=True)
    px4_target = PX4_WORLD_DIR / V2_WORLD.name
    px4_target.write_text(world)

    print("Created:", V2_WORLD)
    print("Copied to PX4:", px4_target)
    print("Removed old round tree includes from V2.")
    print("Added realistic tree models and larger world zones.")
    print("V1 was not modified.")


def main():
    pine_sdf, broadleaf_sdf = create_realistic_tree_models()
    create_realistic_world_v2(pine_sdf, broadleaf_sdf)


if __name__ == "__main__":
    main()