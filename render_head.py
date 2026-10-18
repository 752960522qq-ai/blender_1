import bpy, os, sys
from mathutils import Vector

args=sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
if len(args)!=2: raise SystemExit("Usage: render_head.py <model.blend> <output.png>")
model_path=os.path.abspath(args[0]); output_path=os.path.abspath(args[1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.open_mainfile(filepath=model_path)
scene=bpy.context.scene
meshes=[o for o in scene.objects if o.type=="MESH"]
if not meshes: raise RuntimeError("No mesh found")
bpy.context.view_layer.update()
points=[o.matrix_world@v.co for o in meshes for v in o.data.vertices]
lo=Vector(tuple(min(v[i] for v in points) for i in range(3)))
hi=Vector(tuple(max(v[i] for v in points) for i in range(3)))
center=(lo+hi)*0.5; size=hi-lo; scale=max(size)
center.z+=size.z*0.025

world=bpy.data.worlds.new("Soft warm studio")
world.use_nodes=True
world.node_tree.nodes["Background"].inputs["Color"].default_value=(0.31,0.29,0.28,1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value=0.45
scene.world=world

def area(name, offset, energy, diameter):
    bpy.ops.object.light_add(type="AREA",location=center+Vector(offset)*scale)
    light=bpy.context.object; light.name=name
    light.data.energy=energy; light.data.shape="DISK"; light.data.size=diameter*scale
    light.rotation_euler=(center-light.location).to_track_quat("-Z","Y").to_euler()
area("Key softbox",(-1.8,-2.8,1.8),75,1.4)
area("Front fill",(1.5,-2.0,0.35),32,1.8)
area("Rim",(.4,1.6,1.5),80,1.3)

direction=Vector((0.30,-1.0,0.065)).normalized()
bpy.ops.object.camera_add(location=center+direction*scale*3.4)
camera=bpy.context.object
camera.rotation_euler=(center-camera.location).to_track_quat("-Z","Y").to_euler()
camera.data.type="ORTHO";camera.data.ortho_scale=scale*1.18
scene.camera=camera

scene.render.engine="CYCLES"
scene.cycles.samples=24
scene.cycles.use_denoising=True
scene.render.resolution_x=720
scene.render.resolution_y=900
scene.render.resolution_percentage=100
scene.render.image_settings.file_format="PNG"
scene.render.image_settings.color_mode="RGBA"
scene.view_settings.view_transform="AgX"
scene.view_settings.look="AgX - Medium High Contrast"
scene.render.filepath=output_path
os.makedirs(os.path.dirname(output_path),exist_ok=True)
bpy.ops.render.render(write_still=True)
if not os.path.isfile(output_path) or os.path.getsize(output_path)<10000:
    raise RuntimeError("Render output missing or unexpectedly small")
print("HEAD_RENDER_OK",bpy.app.version_string,output_path,os.path.getsize(output_path),flush=True)
