import bpy
import os

out = os.environ.get("GITHUB_WORKSPACE", os.getcwd())
print("BLENDER_VERSION:", bpy.app.version_string)

# Build a small scene and render with CPU Cycles.
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
cube = bpy.context.object
cube.name = "SmokeTestCube"
mat = bpy.data.materials.new("SmokeTestMaterial")
mat.diffuse_color = (0.12, 0.42, 0.8, 1.0)
cube.data.materials.append(mat)

bpy.ops.object.camera_add(location=(4, -5, 3.5))
camera = bpy.context.object
camera.rotation_euler = (cube.location - camera.location).to_track_quat("-Z", "Y").to_euler()
scene = bpy.context.scene
scene.camera = camera
bpy.ops.object.light_add(type="AREA", location=(2, -3, 5))
bpy.context.object.data.energy = 500

scene.render.engine = "CYCLES"
scene.cycles.samples = 8
scene.render.resolution_x = 256
scene.render.resolution_y = 256
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = os.path.join(out, "render.png")
bpy.ops.render.render(write_still=True)
assert os.path.isfile(scene.render.filepath) and os.path.getsize(scene.render.filepath) > 0
print("CYCLES_RENDER_OK:", scene.render.filepath)

# Export and re-import a GLB, then check the mesh.
glb_path = os.path.join(out, "roundtrip.glb")
bpy.ops.export_scene.gltf(filepath=glb_path, export_format="GLB", use_selection=False)
assert os.path.isfile(glb_path) and os.path.getsize(glb_path) > 0
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb_path)
meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
assert any(obj.name == "SmokeTestCube" for obj in meshes), [obj.name for obj in meshes]
print("GLB_EXPORT_IMPORT_OK:", glb_path, "mesh_count=", len(meshes))
print("BLENDER_ACTIONS_SMOKE_TEST_OK")
