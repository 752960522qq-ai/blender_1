import bpy,os,json,struct
prior=os.path.abspath('prior/jill_skin_matched.blend')
bpy.ops.wm.open_mainfile(filepath=prior)
keep=[]
for o in list(bpy.context.scene.objects):
 if o.type!='MESH':continue
 n=o.name
 if n=='Jill_original_neck_connector' or n.startswith('Replacement_') and any(k in n for k in ['Face_Mat','Eyes_In_Mat','Tearline_Mat','elongated fine eyelashes','fuller individual eyebrow hairs']):keep.append(o)
for o in list(bpy.context.scene.objects):
 if o not in keep:bpy.data.objects.remove(o,do_unlink=True)
for o in keep:
 world=o.matrix_world.copy();o.parent=None;o.matrix_world=world
 bpy.context.view_layer.objects.active=o;o.select_set(True)
# Remove armatures and unrelated datablocks by selection-only export.
bpy.context.view_layer.objects.active=keep[0]
os.makedirs('head-output',exist_ok=True)
out=os.path.abspath('head-output/jill_bright_head_neck_no_hair.glb')
bpy.ops.export_scene.gltf(filepath=out,export_format='GLB',use_selection=True,export_animations=False)
b=open(out,'rb').read();assert struct.unpack_from('<I',b,8)[0]==len(b)
bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=out)
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
assert len(meshes)==len(keep), (len(meshes),len(keep))
assert any('neck_connector' in o.name for o in meshes)
assert not any('Chestnut hair' in o.name or 'Hair_' in o.name for o in meshes)
report={'blender':bpy.app.version_string,'mesh_count':len(meshes),'names':[o.name for o in meshes],'roundtrip':'PASS','glb_bytes':len(b)}
open('head-output/validation.json','w').write(json.dumps(report,indent=2));print('HEAD_NECK_ONLY_VALIDATED',json.dumps(report))
