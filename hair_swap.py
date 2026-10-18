import bpy, os, sys, gzip, json
from mathutils import Vector, Matrix

args = sys.argv[sys.argv.index('--')+1:]
if len(args) != 3:
    raise SystemExit('Usage: hair_swap.py <head.glb.gz> <hair_anchor.glb> <output_dir>')
head_gz, hair_path, out_dir = map(os.path.abspath, args)
os.makedirs(out_dir, exist_ok=True)
head_path = os.path.join(out_dir, 'head_input.glb')
with gzip.open(head_gz, 'rb') as src, open(head_path, 'wb') as dst:
    while True:
        b=src.read(1024*1024)
        if not b: break
        dst.write(b)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=head_path)
head_meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
face = next((o for o in head_meshes if 'face' in o.name.lower()), None)
if face is None:
    raise RuntimeError('Target face mesh was not found: '+repr([o.name for o in head_meshes]))
head_objects = set(bpy.context.scene.objects)
bpy.ops.import_scene.gltf(filepath=hair_path)
source_objects = [o for o in bpy.context.scene.objects if o not in head_objects]
source_meshes = [o for o in source_objects if o.type == 'MESH']
anchor = next((o for o in source_meshes if 'head_ava_normal2' in o.name.lower()), None)
hair_meshes = [o for o in source_meshes if 'hair' in o.name.lower()]
if anchor is None or len(hair_meshes) != 4:
    raise RuntimeError('Hair import incomplete; anchor=%r meshes=%r' % (anchor, [o.name for o in source_meshes]))

def bounds(obj):
    pts=[obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    lo=Vector(tuple(min(p[i] for p in pts) for i in range(3)))
    hi=Vector(tuple(max(p[i] for p in pts) for i in range(3)))
    return lo,hi,(lo+hi)*0.5

slo,shi,sc=bounds(anchor); tlo,thi,tc=bounds(face)
sz=shi.z-slo.z; tz=thi.z-tlo.z
if sz <= 1e-6 or tz <= 1e-6: raise RuntimeError('Invalid anchor/face size')
scale=(tz/sz)*1.015
mapping=Matrix.Translation(tc) @ Matrix.Scale(scale,4) @ Matrix.Translation(-sc)

# Bake source hierarchy transforms into each hair mesh, then fit it to the target head.
for obj in hair_meshes:
    obj.data=obj.data.copy()
    obj.data.transform(obj.matrix_world)
    obj.parent=None
    obj.matrix_world=Matrix.Identity(4)
    obj.data.transform(mapping)
    obj.name='Chestnut hair | '+obj.name
    obj.data.name=obj.name+' mesh'
    for slot in obj.material_slots:
        mat=slot.material
        if mat is None: continue
        mat.use_nodes=True
        nt=mat.node_tree; nodes=nt.nodes; links=nt.links
        principled=next((n for n in nodes if n.type=='BSDF_PRINCIPLED'),None)
        if principled is None: continue
        rough=principled.inputs.get('Roughness')
        if rough: rough.default_value=0.28
        metallic=principled.inputs.get('Metallic')
        if metallic: metallic.default_value=0.0
        spec=principled.inputs.get('Specular IOR Level')
        if spec: spec.default_value=0.38
        coat=principled.inputs.get('Coat Weight')
        if coat: coat.default_value=0.18
        coat_rough=principled.inputs.get('Coat Roughness')
        if coat_rough: coat_rough.default_value=0.24
        base=principled.inputs.get('Base Color')
        if base:
            image_nodes=[n for n in nodes if n.type=='TEX_IMAGE' and n.image is not None]
            for link in list(base.links): links.remove(link)
            if image_nodes:
                multiply=nodes.new('ShaderNodeMixRGB'); multiply.blend_type='MULTIPLY'; multiply.inputs[0].default_value=1.0
                multiply.inputs[2].default_value=(0.46,0.22,0.115,1.0)
                links.new(image_nodes[0].outputs['Color'],multiply.inputs[1]); links.new(multiply.outputs['Color'],base)
            else:
                base.default_value=(0.24,0.085,0.035,1.0)
        mat.diffuse_color=(0.25,0.09,0.04,1.0)
        mat.name='Warm chestnut | soft satin gloss'

# Remove the source-model head anchor and imported hierarchy empties; keep only the target head and fitted hair.
bpy.data.objects.remove(anchor, do_unlink=True)
for obj in source_objects:
    if obj.type != 'MESH': bpy.data.objects.remove(obj, do_unlink=True)

# Save editable project and export only model geometry/materials.
blend_path=os.path.join(out_dir,'head_chestnut_hair.blend')
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
model_meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
bpy.ops.object.select_all(action='DESELECT')
for obj in model_meshes: obj.select_set(True)
bpy.context.view_layer.objects.active=face
model_path=os.path.join(out_dir,'head_chestnut_hair.glb')
bpy.ops.export_scene.gltf(filepath=model_path,export_format='GLB',use_selection=True,export_apply=True,export_yup=True)

# Re-import the exported GLB in a clean file to validate the deliverable.
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=model_path)
check_meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
check_hair=[o for o in check_meshes if 'chestnut hair' in o.name.lower() or 'hair' in o.name.lower()]
if len(check_meshes) < 5 or len(check_hair) != 4:
    raise RuntimeError('GLB round-trip failed: meshes=%s hair=%s' % ([o.name for o in check_meshes],[o.name for o in check_hair]))

# Build three restrained studio views with the muted exposure used in prior previews.
scene=bpy.context.scene
bpy.context.view_layer.update()
points=[o.matrix_world@v.co for o in check_meshes for v in o.data.vertices]
lo=Vector(tuple(min(v[i] for v in points) for i in range(3))); hi=Vector(tuple(max(v[i] for v in points) for i in range(3)))
center=(lo+hi)*0.5; size=hi-lo; scale_scene=max(size)
world=bpy.data.worlds.new('Soft warm studio'); world.use_nodes=True
world.node_tree.nodes['Background'].inputs['Color'].default_value=(0.31,0.29,0.28,1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value=0.22; scene.world=world

def area(name,offset,energy,diameter):
    bpy.ops.object.light_add(type='AREA',location=center+Vector(offset)*scale_scene)
    light=bpy.context.object; light.name=name; light.data.energy=energy; light.data.shape='DISK'; light.data.size=diameter*scale_scene
    light.rotation_euler=(center-light.location).to_track_quat('-Z','Y').to_euler()
area('Key softbox',(-1.8,-2.8,1.8),42,1.4); area('Front fill',(1.5,-2.0,0.35),11,1.8); area('Rim',(.4,1.6,1.5),30,1.3)
bpy.ops.object.camera_add(); camera=bpy.context.object; camera.data.type='ORTHO'; camera.data.ortho_scale=scale_scene*1.24; scene.camera=camera
scene.render.engine='CYCLES'; scene.cycles.samples=24; scene.cycles.use_denoising=True
scene.render.resolution_x=640; scene.render.resolution_y=800; scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'; scene.render.image_settings.color_mode='RGBA'
scene.view_settings.view_transform='AgX'; scene.view_settings.look='AgX - Medium High Contrast'; scene.view_settings.exposure=-0.25
views={'head_front':Vector((0,-1,0.035)),'head_45_degree':Vector((0.707,-0.707,0.04)),'head_profile':Vector((1,0,0.04))}
for name,direction in views.items():
    direction.normalize(); camera.location=center+direction*scale_scene*3.4; camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
    path=os.path.join(out_dir,name+'.png'); scene.render.filepath=path; bpy.ops.render.render(write_still=True)
    if not os.path.isfile(path) or os.path.getsize(path)<10000: raise RuntimeError('Missing render '+path)
    print('HAIR_SWAP_RENDER_OK',name,os.path.getsize(path),flush=True)
report={'blender':bpy.app.version_string,'scale':scale,'source_face_bounds':[list(slo),list(shi)],'target_face_bounds':[list(tlo),list(thi)],'hair_objects':len(check_hair),'total_meshes':len(check_meshes),'roundtrip':'passed','renders':'3 passed'}
with open(os.path.join(out_dir,'hair-swap-report.json'),'w') as f: json.dump(report,f,indent=2)
print('HAIR_SWAP_OK',json.dumps(report),flush=True)
