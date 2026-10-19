import bpy,bmesh,json,gzip,os,sys,struct
from mathutils import Vector
from mathutils.kdtree import KDTree
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
os.makedirs('jill-output',exist_ok=True)
for kind in ['body','head']:
 with gzip.open('models/jill-swap/'+kind+'.glb.gz','rb') as f: data=f.read()
 open('/tmp/'+kind+'.glb','wb').write(data)
bpy.ops.import_scene.gltf(filepath='/tmp/body.glb')
original=list(bpy.context.scene.objects)
arm=next(o for o in original if o.type=='ARMATURE')
face=next(o for o in original if o.type=='MESH' and 'Face_Mat' in o.name)
# Cache face surface and skin weights before retaining only its neck section.
kdt=KDTree(len(face.data.vertices)); weights=[]
for v in face.data.vertices:
 p=face.matrix_world@v.co;kdt.insert(p,v.index)
 weights.append([(face.vertex_groups[g.group].name,g.weight) for g in v.groups if g.weight>0.00001])
kdt.balance()
head_bone=next(b.name for b in arm.data.bones if b.name=='head')
# Keep original lower neck, as the replacement head stops above the torso seam.
bm=bmesh.new();bm.from_mesh(face.data)
cut=bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-7,plane_co=(0,0,1.478),plane_no=(0,0,1),clear_outer=True,clear_inner=False)
bm.to_mesh(face.data);bm.free();face.data.update();face.name='Jill_original_neck_connector'
for o in original:
 if o.type=='MESH' and o!=face and any(s in o.name for s in ['Eyelash_Mat','Tearline_Mat','Eyes_Out_Mat','Eyes_In_Mat','Jill_RE3_Hair']):
  bpy.data.objects.remove(o,do_unlink=True)
before=set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath='/tmp/head.glb')
new=[o for o in bpy.data.objects if o not in before and o.type=='MESH']
assert len(new)==9,len(new)
report={'blender':bpy.app.version_string,'source_meshes':len(new),'head_bone':head_bone,'parts':[]}
for o in new:
 # Source is centered on eye height, glTF +Y maps to Blender +Z.
 mw=o.matrix_world.copy();mw.translation+=Vector((0,0,1.5889999866485596));o.matrix_world=mw
 # Bake coordinates in armature object space, retaining the original shape/UVs.
 transform=arm.matrix_world.inverted()@o.matrix_world
 for v in o.data.vertices:v.co=transform@v.co
 o.parent=arm;o.matrix_parent_inverse.identity();o.matrix_basis.identity()
 groups={}
 hair='Chestnut hair' in o.name
 for v in o.data.vertices:
  if hair: pairs=[(head_bone,1.0)]
  else:
   _,ind,_=kdt.find(arm.matrix_world@v.co);pairs=weights[ind] or [(head_bone,1.0)]
  total=sum(w for _,w in pairs)
  for name,w in pairs:
   if name not in groups:groups[name]=o.vertex_groups.new(name=name)
   groups[name].add([v.index],w/total,'REPLACE')
 mod=o.modifiers.new('Jill skeleton','ARMATURE');mod.object=arm
 o.name='Replacement_'+o.name
 report['parts'].append({'name':o.name,'vertices':len(o.data.vertices),'groups':len(groups)})
bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath('jill-output/jill_head_hair_replaced.blend'))
out=os.path.abspath('jill-output/jill_head_hair_replaced.glb')
bpy.ops.export_scene.gltf(filepath=out,export_format='GLB',export_animations=False,export_yup=True,export_all_influences=True)
# Verify exact GLB container framing, then use Blender importer in a clean scene.
b=open(out,'rb').read();magic,version,total=struct.unpack_from('<4sII',b);assert magic==b'glTF' and total==len(b)
p=12
while p<len(b):
 n,t=struct.unpack_from('<I4s',b,p);assert t in (b'JSON',b'BIN\x00');p+=8+n
assert p==len(b)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=out)
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
assert len([o for o in meshes if o.name.startswith('Replacement_')])==9
assert any(o.type=='ARMATURE' for o in bpy.context.scene.objects)
for o in meshes:
 assert len(o.data.vertices)>0
 if o.name.startswith('Replacement_'):assert any(m.type=='ARMATURE' and m.object for m in o.modifiers)
report.update({'roundtrip_import':'PASS','mesh_count':len(meshes),'glb_bytes':len(b),'container_check':'PASS'})
open('jill-output/validation.json','w').write(json.dumps(report,indent=2))
print('JILL_HEAD_SWAP_VALIDATED',json.dumps(report))
