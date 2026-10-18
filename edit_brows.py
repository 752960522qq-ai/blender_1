import bpy,sys,os,json,hashlib
import numpy as np
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from brow_geometry import densify

source,outdir=sys.argv[sys.argv.index('--')+1:]
os.makedirs(outdir,exist_ok=True)
assert hashlib.sha256(open(source,'rb').read()).hexdigest()=='ecf0b6e6aba82653ba36ede8c03d64a9f3deef660ac727d87bfd2ad2391e4a90'
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(source))
bpy.context.view_layer.update()
objects=[o for o in bpy.context.scene.objects if o.type=='MESH']
brow=next(o for o in objects if 'eyebrow' in o.name)

def fingerprint(mesh):
    v=np.empty(len(mesh.vertices)*3,dtype=np.float32);mesh.vertices.foreach_get('co',v)
    return hashlib.sha256(v.tobytes()).hexdigest()
def textures():
    hashes=[]
    for im in bpy.data.images:
        if im.size[0] and im.size[1] and im.type!='RENDER_RESULT':
            pixels=np.empty(len(im.pixels),dtype=np.float32);im.pixels.foreach_get(pixels)
            hashes.append(hashlib.sha256(pixels.tobytes()).hexdigest())
    return sorted(hashes)
others={o.name:fingerprint(o.data) for o in objects if o!=brow};image_hashes=textures()
mesh=brow.data;mesh.calc_loop_triangles()
tri=np.array([t.vertices[:] for t in mesh.loop_triangles],dtype=np.int32)
v=np.empty(len(mesh.vertices)*3);mesh.vertices.foreach_get('co',v);v=v.reshape(-1,3)
M=np.array(brow.matrix_world,dtype=float);A=M[:3,:3]
w=v@A.T+M[:3,3];p=w[:,[0,2,1]]*np.array([1,1,-1])
new,faces,stats=densify(p,tri)
wnew=new[:,[0,2,1]]*np.array([1,-1,1]);local=(wnew-M[:3,3])@np.linalg.inv(A).T
newmesh=bpy.data.meshes.new('Dense natural eyebrow hairs')
newmesh.from_pydata(local.tolist(),[],faces.tolist());newmesh.update()
for mat in mesh.materials:newmesh.materials.append(mat)
for polygon in newmesh.polygons:polygon.use_smooth=True
brow.data=newmesh
for mat in newmesh.materials:
    if mat.use_nodes:
        node=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
        rgba=list(node.inputs['Base Color'].default_value)
        node.inputs['Base Color'].default_value=tuple(c*.85 for c in rgba[:3])+(rgba[3],)
assert others=={o.name:fingerprint(o.data) for o in objects if o!=brow}
assert textures()==image_hashes
report={'blender_version':bpy.app.version_string,'eyebrows':stats,'non_brow_geometry_unchanged':True,'textures_unchanged':True,'rendering_performed':False}
blend=os.path.abspath(os.path.join(outdir,'head_dense_brows.blend'))
glb=os.path.abspath(os.path.join(outdir,'head_dense_brows.glb'))
bpy.ops.wm.save_as_mainfile(filepath=blend)
bpy.ops.export_scene.gltf(filepath=glb,export_format='GLB',export_yup=True,export_normals=True,export_texcoords=True,export_materials='EXPORT',export_animations=False)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
reloaded=[o for o in bpy.context.scene.objects if o.type=='MESH'];assert len(reloaded)==5
assert textures()==image_hashes
rb=next(o for o in reloaded if 'eyebrow' in o.name);rb.data.calc_loop_triangles()
assert len(rb.data.loop_triangles)==stats['triangles_after']
report['glb_reimport']='passed';report['output_sha256']=hashlib.sha256(open(glb,'rb').read()).hexdigest()
with open(os.path.join(outdir,'brow-report.json'),'w') as f:json.dump(report,f,indent=2)
print('BROW_EDIT_SUCCESS',json.dumps(report),flush=True)
