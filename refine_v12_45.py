"""Conservative symmetric lower-cheek fairing for an uploaded head GLB.

Run with:
    blender -b --factory-startup --python-exit-code 1 --python refine_v12_45.py -- \
        MODEL.glb REFERENCE.png OUTPUT_DIR refine

"smoke" runs the same geometry checks on a repository test model without claiming
that it is the user's current model. The reference is kept only in the .blend
camera background, never in the output GLB.

Safety: preserve all original feature-region vertices, preserve both lateral
cheek/jaw anchors, cap any moved vertex at 0.35 mm, preserve UV/material/image
assets, and fail closed when geometry assumptions cannot be verified.
"""
import os
import sys
import json
import math
import hashlib
import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
if len(argv) != 4:
    raise SystemExit("Usage: -- INPUT.glb REF_IMAGE_OR_EMPTY OUT_DIR smoke|refine")
source, reference, out_dir, mode = argv
source, out_dir = os.path.abspath(source), os.path.abspath(out_dir)
reference = os.path.abspath(reference) if reference else ""
if mode not in {"smoke", "refine"}:
    raise ValueError("Unknown mode")
if not os.path.isfile(source) or not source.lower().endswith(".glb"):
    raise FileNotFoundError("Missing input GLB: " + source)
if mode == "refine" and not os.path.isfile(reference):
    raise FileNotFoundError("The 45 degree reference portrait must be present")
if reference and not reference.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
    raise ValueError("Reference must be an image")
os.makedirs(out_dir, exist_ok=True)

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for piece in iter(lambda: f.read(1024 * 1024), b""):
            h.update(piece)
    return h.hexdigest()

def smoothstep(a, b, value):
    t = np.clip((value - a) / (b-a), 0.0, 1.0)
    return t*t*(3.0-2.0*t)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=source)
bpy.context.view_layer.update()
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    raise RuntimeError("No meshes in source GLB")
mesh_names = [o.name for o in meshes]
face_candidates = [o for o in meshes if "face" in o.name.lower() and len(o.data.vertices) > 2000]
face = max(face_candidates or meshes, key=lambda o: len(o.data.polygons))
if len(face.data.vertices) < 1000:
    raise RuntimeError("No sufficiently detailed head mesh could be identified")

original_materials = [(o.name, [m.name if m else "" for m in o.data.materials]) for o in meshes]
original_images = sorted([(im.name, tuple(im.size)) for im in bpy.data.images if im.has_data])
original_uvs = {o.name: len(o.data.uv_layers) for o in meshes}
original_counts = {o.name: {"vertices": len(o.data.vertices), "faces": len(o.data.polygons)} for o in meshes}

# Imported Blender GLB faces negative Y; X is left-right and Z is up.
# Calculate the edit mask in WORLD coordinates, not object-local coordinates.
mesh = face.data
coordinates = np.zeros(len(mesh.vertices)*3, dtype=np.float64)
mesh.vertices.foreach_get("co", coordinates)
coordinates = coordinates.reshape(-1, 3)
matrix = np.array(face.matrix_world, dtype=np.float64)
world = coordinates @ matrix[:3,:3].T + matrix[:3,3]
bounds_low = np.min(world, axis=0)
bounds_high = np.max(world, axis=0)
height = float(bounds_high[2]-bounds_low[2])
width = float(bounds_high[0]-bounds_low[0])
if not 0.09 < height < 2.0 or not 0.07 < width < 2.0:
    raise RuntimeError("Model dimensions atypical: fail closed rather than edit features")
mid_x = float((bounds_low[0]+bounds_high[0])/2)
# Work in head-scale percentages: cheek around lower middle of face,
# excluding the middle of the face and the lower neck.
relz = (world[:,2]-bounds_low[2])/height
relx = np.abs(world[:,0]-mid_x)/(width*0.5)
# Face cheeks: restricted side zones, beneath eyes and above lower neck.
mask = smoothstep(0.32, 0.52, relx) * (1-smoothstep(0.94, 1.02, relx))
mask *= smoothstep(0.36, 0.45, relz) * (1-smoothstep(0.69, 0.78, relz))
# Protect central nose/mouth and eye-region regardless of geometry.
mask *= (relz < 0.78)

# Detect one characteristic lateral cheek-jaw prominence per side.
# The farthest lateral sample is a stable anchor (preserve exact coordinates);
# its immediate neighborhood is locked too.
anchors = []
for sign in (-1,1):
    cand = np.where(((world[:,0]-mid_x)*sign > width*0.19) &
                    (relz > 0.40) & (relz < 0.72))[0]
    if len(cand) < 30:
        raise RuntimeError("Could not identify bilateral cheek-anchor regions")
    lateral = (world[cand,0]-mid_x)*sign
    apex = int(cand[np.argmax(lateral)])
    anchors.append(apex)
    # Lock apex neighborhood using a 7 mm radius for a 17 cm wide head.
    dist = np.linalg.norm(world - world[apex],axis=1)
    rad = width * (0.007/0.17)
    mask *= smoothstep(rad*0.85, rad*1.8, dist)

# Freeze UV seams as groups of coincident 3D vertices.
# This avoids different displacements for two vertices at the same physical point.
key, inverse = np.unique(np.round(world, 7), axis=0, return_inverse=True)
n = len(key)
counts = np.bincount(inverse, minlength=n)
u = np.zeros((n,3))
np.add.at(u, inverse, world)
u /= counts[:,None]
wmask = np.zeros(n)
np.add.at(wmask, inverse, mask)
wmask /= counts
for anchor in anchors:
    wmask[inverse[anchor]] = 0
mesh.calc_loop_triangles()
tris = np.array([t.vertices[:] for t in mesh.loop_triangles], dtype=np.int32)
edges = np.concatenate((tris[:,[0,1]], tris[:,[1,2]], tris[:,[2,0]]), axis=0)
edges = np.sort(inverse[edges], axis=1)
edges = np.unique(edges[edges[:,0] != edges[:,1]], axis=0)
a,b = edges[:,0],edges[:,1]
degree = np.bincount(edges.ravel(),minlength=n).astype(float)
if np.sum(wmask>0.05) < 60:
    raise RuntimeError("Insufficient cheek-region coverage, refusing edit")

# Very small, area-restricted Laplacian fairing. Never modify the forehead,
# eyelids, eyeballs, brows, nose, mouth, ear, or texture UV coordinates.
p = u.copy()
for _ in range(9):
    sums = np.zeros_like(p)
    np.add.at(sums,a,p[b])
    np.add.at(sums,b,p[a])
    average = sums / np.maximum(degree[:,None],1)
    p += 0.08*wmask[:,None]*(average-p)
delta = p-u
limit_m = min(.00035, width*0.002)
dlen=np.linalg.norm(delta,axis=1)
delta *= np.minimum(1, limit_m/np.maximum(dlen,1e-12))[:,None]

# Symmetry: mirror tiny adjustments to the opposite side on paired positions,
# but never overwrite an anchor or another protected vertex.
kdtree = KDTree(n)
for i, vec in enumerate(u):
    kdtree.insert(tuple(vec),i)
kdtree.balance()
paired = 0
newdelta = delta.copy()
for i in range(n):
    if wmask[i] <= 0 or u[i,0] <= mid_x + width*0.1:
        continue
    mirror = (2*mid_x-u[i,0],u[i,1],u[i,2])
    _, j, distance = kdtree.find(mirror)
    if distance > width*0.015 or wmask[j] <= 0:
        continue
    mirrored = np.array([-delta[j,0],delta[j,1],delta[j,2]])
    avg = (delta[i]+mirrored)*0.5
    newdelta[i] = avg
    newdelta[j] = [-avg[0],avg[1],avg[2]]
    paired += 1
delta = newdelta
delta[wmask<=1e-10] = 0
modified_world = world + delta[inverse]
anchor_shift = [float(np.linalg.norm(modified_world[i]-world[i])) for i in anchors]
if any(shift > 1e-10 for shift in anchor_shift):
    raise RuntimeError("Protected cheek prominence moved")
displacement = np.linalg.norm(modified_world-world,axis=1)
if float(displacement.max()) > limit_m+1e-9:
    raise RuntimeError("A vertex moved beyond safe limit")
if not np.isfinite(modified_world).all():
    raise RuntimeError("Nonfinite vertices")

# Update only the face mesh geometry; material slots / UV coordinates unchanged.
local = (modified_world - matrix[:3,3]) @ np.linalg.inv(matrix[:3,:3]).T
mesh.vertices.foreach_set("co", local.astype(np.float32).ravel())
mesh.update()
smoothed_vertices = int(np.sum(displacement>1e-6))

# Trim only a small lower-neck tail by a planar bisect.
# Deliberately do not decimate the face or touch the upper neck.
cut_world_height = float(bounds_low[2]+height*0.105)
def trim_lower_neck(obj):
    bm=bmesh.new()
    bm.from_mesh(obj.data)
    mw=obj.matrix_world
    world_plane=Vector((0,0,cut_world_height))
    plane_co=mw.inverted()@world_plane
    plane_no=(mw.transposed().to_3x3()@Vector((0,0,1))).normalized()
    bmesh.ops.bisect_plane(
        bm, geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
        dist=0.000001, plane_co=plane_co, plane_no=plane_no,
        clear_inner=True, clear_outer=False)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

trim_lower_neck(face)
if any(not np.isfinite(tuple(v.co)).all() for v in face.data.vertices):
    raise RuntimeError("Neck trim produced bad coordinates")
if original_uvs[face.name] != len(face.data.uv_layers):
    raise RuntimeError("UV layers were damaged by neck trim")

# Reference remains a packed, semitransparent CAMERA BACKGROUND in the .blend;
# it is not a visible texture plane and never enters the exported GLB.
image_added=False
if reference:
    zmin,zmax = bounds_low[2],bounds_high[2]
    center = Vector((mid_x,float((bounds_low[1]+bounds_high[1])/2),float((zmin+zmax)/2)))
    distance=max(height*3.0,0.5)
    camera_data=bpy.data.cameras.new("Reference 45 Degree - Orthographic")
    camera_data.type="ORTHO"
    camera_data.ortho_scale=height*1.13
    camera=bpy.data.objects.new("Reference 45 Degree - Orthographic",camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location=center+Vector((distance*0.70710678,-distance*0.70710678,0))
    camera.rotation_euler=(center-camera.location).to_track_quat("-Z","Y").to_euler()
    bpy.context.scene.camera=camera
    camera_data.show_background_images=True
    bg=camera_data.background_images.new()
    bg.image=bpy.data.images.load(reference)
    bg.image.pack()
    bg.alpha=0.48
    bg.display_depth="BACK"
    bg.frame_method="FIT"
    image_added=True

blend=os.path.join(out_dir,"head_v12_45_review.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend)

# Explicitly export original meshes only; keeps camera reference out of GLB.
bpy.ops.object.select_all(action="DESELECT")
for obj in meshes:
    obj.select_set(True)
bpy.context.view_layer.objects.active=face
dest=os.path.join(out_dir,"head_v12_45_refined.glb")
bpy.ops.export_scene.gltf(filepath=dest,export_format="GLB",
                         use_selection=True, export_normals=True,
                         export_texcoords=True, export_materials="EXPORT",
                         export_animations=False)
if os.path.getsize(dest)<10000:
    raise RuntimeError("GLB export is unexpectedly empty")

# Re-import the actual exported file: preserve mesh/material inventory and images.
after_faces = {obj.name:len(obj.data.polygons) for obj in meshes}
if any(after_faces[k] > original_counts[k]["faces"]+500 for k in after_faces):
    raise RuntimeError("Unexpected mesh-face growth")
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=dest)
reloaded=[o for o in bpy.context.scene.objects if o.type=="MESH"]
if len(reloaded)!=len(meshes):
    raise RuntimeError("Roundtrip mesh count changed")
if len(bpy.data.materials)<len(set(m for _,names in original_materials for m in names if m)):
    raise RuntimeError("Roundtrip materials are missing")
report={
    "status":"PASS",
    "mode":mode,
    "blender_version":bpy.app.version_string,
    "source_sha256":sha256(source),
    "reference_present":image_added,
    "source_meshes":mesh_names,
    "edited_mesh":face.name,
    "initial_geometry":original_counts,
    "after_edit_polygons":after_faces,
    "apex_world_coordinates":[world[i].tolist() for i in anchors],
    "anchor_displacement_mm":[x*1000 for x in anchor_shift],
    "vertices_smoothed_over_0_001mm":smoothed_vertices,
    "max_surface_displacement_mm":float(displacement.max()*1000),
    "paired_mirror_vertices":paired,
    "lower_neck_cut_height_world":cut_world_height,
    "original_materials":original_materials,
    "original_image_dimensions":original_images,
    "original_uv_layer_counts":original_uvs,
    "output_mesh_count":len(reloaded),
    "output_material_count":len(bpy.data.materials),
    "output_sha256":sha256(dest),
    "not_a_pixel_perfect_automatic_portrait_fit":True
}
with open(os.path.join(out_dir,"report.json"),"w") as f:
    json.dump(report,f,indent=2,ensure_ascii=False)
print("HEAD_V12_45_EDIT_OK",json.dumps(report,ensure_ascii=False),flush=True)
