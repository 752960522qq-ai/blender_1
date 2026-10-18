import bpy
import os
import sys
from mathutils import Vector

# Run with:
# blender -b --python review_model.py -- /path/to/model.blend output_dir
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(args) != 2:
    raise SystemExit("Usage: review_model.py <model.blend|model.glb> <output_dir>")

model_path = os.path.abspath(args[0])
output_dir = os.path.abspath(args[1])
os.makedirs(output_dir, exist_ok=True)
if not os.path.isfile(model_path):
    raise FileNotFoundError(model_path)

bpy.ops.wm.read_factory_settings(use_empty=True)
if model_path.lower().endswith(".blend"):
    bpy.ops.wm.open_mainfile(filepath=model_path)
elif model_path.lower().endswith(".glb") or model_path.lower().endswith(".gltf"):
    bpy.ops.import_scene.gltf(filepath=model_path)
else:
    raise ValueError("Input must be a .blend, .glb, or .gltf file")

scene = bpy.context.scene
meshes = [obj for obj in scene.objects if obj.type == "MESH"]
if not meshes:
    raise RuntimeError("No mesh objects found in model")
bpy.context.view_layer.update()

world_points = [obj.matrix_world @ vertex.co for obj in meshes for vertex in obj.data.vertices]
bounds_min = Vector(tuple(min(v[i] for v in world_points) for i in range(3)))
bounds_max = Vector(tuple(max(v[i] for v in world_points) for i in range(3)))
center = (bounds_min + bounds_max) * 0.5
size = bounds_max - bounds_min
scale = max(size)
if scale <= 0:
    raise RuntimeError("Model has empty or degenerate bounds")

# Use predictable studio lighting while preserving the model's materials and textures.
for obj in list(scene.objects):
    if obj.type in {"CAMERA", "LIGHT"}:
        bpy.data.objects.remove(obj, do_unlink=True)

world = bpy.data.worlds.new("Visual Review World")
world.use_nodes = True
background = world.node_tree.nodes.get("Background")
background.inputs["Color"].default_value = (0.32, 0.30, 0.29, 1.0)
background.inputs["Strength"].default_value = 0.28
scene.world = world

def add_area(name, offset, power, light_size):
    bpy.ops.object.light_add(type="AREA", location=center + Vector(offset) * scale)
    light = bpy.context.object
    light.name = name
    light.data.energy = power
    light.data.shape = "DISK"
    light.data.size = light_size * scale
    light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()

add_area("Review Key", (-2.2, -3.4, 2.8), 5.0, 1.8)
add_area("Review Fill", (3.4, -2.0, 0.5), 2.0, 2.4)
add_area("Review Rim", (0.6, 2.8, 2.0), 6.0, 1.7)

scene.render.engine = "CYCLES"
scene.cycles.samples = 12
scene.render.resolution_x = 720
scene.render.resolution_y = 800
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False
scene.view_settings.view_transform = "AgX"

views = [
    ("front", Vector((0.0, -1.0, 0.0))),
    ("three_quarter", Vector((0.72, -0.70, 0.0)).normalized()),
    ("profile", Vector((1.0, 0.0, 0.0))),
]
for name, direction in views:
    location = center + direction * (scale * 3.0) + Vector((0.0, 0.0, scale * 0.06))
    bpy.ops.object.camera_add(location=location)
    camera = bpy.context.object
    camera.name = "Review Camera " + name
    camera.rotation_euler = (center - location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = scale * 1.28
    scene.camera = camera
    scene.render.filepath = os.path.join(output_dir, name + ".png")
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(camera, do_unlink=True)

# Save a temporary file with a fitted material-preview viewport so a GUI runner
# can capture the real Blender interface under Xvfb.
scene.camera = None
for obj in list(scene.objects):
    if obj.type != "MESH":
        obj.hide_set(True)
for obj in meshes:
    obj.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
front_rotation = Vector((0.0, -1.0, 0.0)).to_track_quat("Z", "Y")
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == "VIEW_3D":
            space = area.spaces.active
            space.region_3d.view_location = center
            space.region_3d.view_distance = scale * 2.8
            space.region_3d.view_rotation = front_rotation
            space.region_3d.view_perspective = "ORTHO"
            space.shading.type = "MATERIAL"
            space.overlay.show_overlays = False
viewport_file = os.path.join(output_dir, "viewport-review.blend")
bpy.ops.wm.save_as_mainfile(filepath=viewport_file)

report_path = os.path.join(output_dir, "model-review.txt")
with open(report_path, "w", encoding="utf-8") as report:
    report.write("Blender visual review\n")
    report.write("Blender version: " + bpy.app.version_string + "\n")
    report.write("Input: " + os.path.basename(model_path) + "\n")
    report.write("Mesh objects: " + str(len(meshes)) + "\n")
    report.write("Bounds (X,Y,Z): " + ", ".join(f"{v:.6f}" for v in size) + "\n")
    report.write("Meshes:\n")
    for obj in meshes:
        report.write(f"- {obj.name}: {len(obj.data.vertices)} vertices, {len(obj.data.polygons)} faces\n")
    report.write("Images: front.png, three_quarter.png, profile.png, blender-interface.png\n")
print("VISUAL_REVIEW_OK", report_path)
