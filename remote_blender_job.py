"""Reusable, fail-fast GitHub Actions Blender model validation job.

Inputs (after --): model_path reference_image_or_empty output_directory
No geometry modifications are applied. Camera reference stays in the .blend project.
"""
import bpy
import hashlib
import json
import os
import sys
from mathutils import Vector

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

args = sys.argv[sys.argv.index("--") + 1:]
if len(args) != 3:
    raise RuntimeError("Usage: -- MODEL_PATH REFERENCE_PATH_OR_EMPTY OUTPUT_DIR")
source, reference, output_dir = args
source = os.path.abspath(source)
output_dir = os.path.abspath(output_dir)
os.makedirs(output_dir, exist_ok=True)
if not os.path.isfile(source):
    raise FileNotFoundError(source)
if not source.lower().endswith((".glb", ".gltf", ".blend")):
    raise ValueError("Source model must be GLB, glTF, or blend")

bpy.ops.wm.read_factory_settings(use_empty=True)
if source.lower().endswith(".blend"):
    bpy.ops.wm.open_mainfile(filepath=source)
else:
    bpy.ops.import_scene.gltf(filepath=source)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    raise RuntimeError("No meshes imported")

def mesh_stats(objects):
    polygons, vertices = 0, 0
    bounds = []
    for o in objects:
        polygons += len(o.data.polygons)
        vertices += len(o.data.vertices)
        bounds.extend(o.matrix_world @ Vector(p) for p in o.bound_box)
    return {
        "mesh_count": len(objects),
        "vertices": vertices,
        "polygons": polygons,
        "bounds_min": [min(p[i] for p in bounds) for i in range(3)],
        "bounds_max": [max(p[i] for p in bounds) for i in range(3)],
    }

before = mesh_stats(meshes)
# Use Blender's camera-background image feature: visible in camera view, not as a
# physical plane; never include the reference portrait in the GLB output.
if reference:
    if not os.path.isfile(reference):
        raise FileNotFoundError(reference)
    if not reference.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        raise ValueError("Reference must be PNG/JPEG/WEBP")
    cam_data = bpy.data.cameras.new("ReferenceFrontOrthoCamera")
    cam_data.type = "ORTHO"
    world_min = before["bounds_min"]
    world_max = before["bounds_max"]
    cx = (world_min[0] + world_max[0]) * 0.5
    cy = (world_min[1] + world_max[1]) * 0.5
    cz = (world_min[2] + world_max[2]) * 0.5
    cam_data.ortho_scale = max(0.1, (world_max[2]-world_min[2]) * 1.15)
    cam = bpy.data.objects.new("ReferenceFrontOrthoCamera", cam_data)
    bpy.context.collection.objects.link(cam)
    distance = max(1.0, (world_max[1] - world_min[1]) * 5.0)
    cam.location = (cx, world_min[1] - distance, cz)
    target = Vector((cx, cy, cz))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    cam_data.show_background_images = True
    background = cam_data.background_images.new()
    background.image = bpy.data.images.load(reference)
    background.alpha = 0.5
    background.display_depth = "BACK"
    background.frame_method = "FIT"

scene_path = os.path.join(output_dir, "model_review_scene.blend")
bpy.ops.wm.save_as_mainfile(filepath=scene_path)
glb_path = os.path.join(output_dir, "model_roundtrip.glb")
# Intentionally export only meshes (not the background image/camera).
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.export_scene.gltf(
    filepath=glb_path, export_format="GLB", use_selection=True,
    export_animations=False
)
if os.path.getsize(glb_path) < 128:
    raise RuntimeError("Empty GLB")

# Validate the exported model with a real second import.
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb_path)
after_meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
after = mesh_stats(after_meshes)
if before["mesh_count"] != after["mesh_count"]:
    raise AssertionError(f"Mesh count changed: {before} => {after}")
if before["polygons"] != after["polygons"]:
    raise AssertionError(f"Polygon count changed: {before} => {after}")
if before["vertices"] != after["vertices"]:
    raise AssertionError(f"Vertex count changed: {before} => {after}")
report = {
    "result": "PASS",
    "blender_version": bpy.app.version_string,
    "model_sha256": sha256_file(source),
    "reference_used": bool(reference),
    "model_geometry_modified": False,
    "input": before,
    "reimported": after,
    "output_glb_sha256": sha256_file(glb_path),
}
report_file = os.path.join(output_dir, "validation_report.json")
with open(report_file, "w", encoding="utf8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print("REMOTE_BLENDER_MODEL_CHECK_OK", json.dumps(report, ensure_ascii=False), flush=True)
