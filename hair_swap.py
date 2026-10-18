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
depth_scale=((thi.y-tlo.y)/(shi.y-slo.y)*1.015)/scale
mapping=Matrix.Translation(tc) @ Matrix.Diagonal((1.0,depth_scale,1.0,1.0)) @ Matrix.Scale(scale,4) @ Matrix.Translation(-sc)

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
        if spec: spec.default_value=0.22
        ior=principled.inputs.get('IOR')
        if ior: ior.default_value=1.45
        coat=principled.inputs.get('Coat Weight')
        if coat: coat.default_value=0.10
        coat_rough=principled.inputs.get('Coat Roughness')
        if coat_rough: coat_rough.default_value=0.28
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
for obj in source_objects:
    if obj != anchor and obj.type != 'MESH': bpy.data.objects.remove(obj, do_unlink=True)
bpy.data.objects.remove(anchor, do_unlink=True)

# Correct local strand/head collisions while keeping the face mesh unchanged.
import bmesh, hashlib
from mathutils.bvhtree import BVHTree
bpy.context.view_layer.update()
face.data.calc_loop_triangles()
head_points=[face.matrix_world @ v.co for v in face.data.vertices]
head_tris=[tuple(t.vertices) for t in face.data.loop_triangles]
head_bvh=BVHTree.FromPolygons(head_points,head_tris,all_triangles=True)
hull=bmesh.new()
for p in head_points: hull.verts.new(p)
bmesh.ops.convex_hull(hull,input=list(hull.verts),use_existing_faces=False)
hull.verts.index_update()
hull_bvh=BVHTree.FromPolygons([v.co.copy() for v in hull.verts],[[v.index for v in f.verts] for f in hull.faces])
hull.free()
clearance=0.003
zfloor=tlo.z+0.002

def correction(p):
    direction=p-tc
    radius=direction.length
    if radius<1e-8: return Vector((0,0,0))
    direction/=radius
    loc,n,idx,d=hull_bvh.ray_cast(tc+direction*0.6,-direction,1.2)
    if loc is None: return Vector((0,0,0))
    surface_radius=(loc-tc).dot(direction)
    needed=surface_radius+clearance-radius
    return direction*max(0.0,needed)

def collision_stats(obj):
    mesh=obj.data; mesh.calc_loop_triangles()
    pts=[v.co.copy() for v in mesh.vertices]
    tris=[tuple(t.vertices) for t in mesh.loop_triangles]
    overlap=len(BVHTree.FromPolygons(pts,tris,all_triangles=True).overlap(head_bvh))
    inside=0
    for p in pts:
        if p.z < zfloor: continue
        loc,n,idx,d=head_bvh.find_nearest(p)
        if loc is not None and d<0.045 and (p-loc).dot(n)<-0.00005: inside+=1
    return {'vertices':len(pts),'inside_vertices':inside,'triangle_intersection_pairs':overlap}

fit_report=[]
for obj in hair_meshes:
    before=collision_stats(obj)
    bm=bmesh.new(); bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm,faces=list(bm.faces))
    # Add only the resolution needed for local clearance around the head.
    for _ in range(2):
        edges=[e for e in bm.edges if e.calc_length()>0.004 and any(v.co.z>zfloor and head_bvh.find_nearest(v.co)[3]<0.04 for v in e.verts)]
        if not edges: break
        bmesh.ops.subdivide_edges(bm,edges=edges,cuts=1,use_grid_fill=True)
    bmesh.ops.triangulate(bm,faces=list(bm.faces))
    bm.to_mesh(obj.data); bm.free(); obj.data.update()
    obj.data.calc_loop_triangles()
    tris=[tuple(t.vertices) for t in obj.data.loop_triangles]
    pts=[v.co.copy() for v in obj.data.vertices]
    original=[p.copy() for p in pts]
    neighbors=[set() for p in pts]
    for a,b,c in tris:
        neighbors[a].update((b,c)); neighbors[b].update((a,c)); neighbors[c].update((a,b))
    for iteration in range(12):
        for i,p in enumerate(pts): pts[i]=p+correction(p)
        shifts=[Vector((0,0,0)) for p in pts]
        for a,b,c in tris:
            samples=[(pts[a]+pts[b])*0.5,(pts[b]+pts[c])*0.5,(pts[c]+pts[a])*0.5,(pts[a]+pts[b]+pts[c])/3]
            delta=max((correction(p) for p in samples),key=lambda v:v.length_squared)
            if delta.length_squared>1e-14:
                for k in (a,b,c):
                    if delta.length_squared>shifts[k].length_squared: shifts[k]=delta
        pts=[p+d for p,d in zip(pts,shifts)]
        # Smooth the deformation field, not the original textured strand shape.
        if iteration<5:
            disp=[p-o for p,o in zip(pts,original)]
            pts=[original[i]+disp[i]*0.75+sum((disp[k] for k in nb),Vector())*(0.25/len(nb)) if nb else pts[i] for i,nb in enumerate(neighbors)]
    for i,p in enumerate(pts): obj.data.vertices[i].co=p+correction(p)
    obj.data.update()
    after=collision_stats(obj)
    fit_report.append({'object':obj.name,'before':before,'after':after,'max_local_move_mm':max((v.co-o).length for v,o in zip(obj.data.vertices,original))*1000})
    print('FIT_OBJECT',json.dumps(fit_report[-1]),flush=True)

# Save editable project and export only model geometry/materials.
blend_path=os.path.join(out_dir,'head_chestnut_hair.blend')
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
model_meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
bpy.ops.object.select_all(action='DESELECT')
for obj in model_meshes: obj.select_set(True)
bpy.context.view_layer.objects.active=face
model_path=os.path.join(out_dir,'head_chestnut_hair.glb')
bpy.ops.export_scene.gltf(filepath=model_path,export_format='GLB',use_selection=True,export_apply=True,export_yup=True)

# glTF's Blender exporter omits arbitrary MixRGB tint nodes from baseColorFactor.
# Patch each hair material factor in the GLB so the chestnut tint survives in viewers.
import struct
with open(model_path,'rb') as f: glb=f.read()
magic,total=struct.unpack_from('<4sI',glb,0)
if magic != b'glTF': raise RuntimeError('Unexpected GLB header')
json_len,json_type=struct.unpack_from('<I4s',glb,12)
if json_type != b'JSON': raise RuntimeError('GLB has no leading JSON chunk')
doc=json.loads(glb[20:20+json_len].decode('utf-8').rstrip(' \t\r\n\0'))
for material in doc.get('materials',[]):
    if material.get('name','').lower().startswith('warm chestnut'):
        pbr=material.setdefault('pbrMetallicRoughness',{})
        pbr['baseColorFactor']=[0.45,0.22,0.115,1.0]
        pbr['metallicFactor']=0.0
        pbr['roughnessFactor']=0.34
        ext=material.setdefault('extensions',{})
        if 'KHR_materials_ior' in ext: ext['KHR_materials_ior']['ior']=1.45
        if 'KHR_materials_specular' in ext:
            ext['KHR_materials_specular']['specularFactor']=0.20
            ext['KHR_materials_specular'].pop('specularColorFactor',None)
doc['extensionsUsed']=[x for x in doc.get('extensionsUsed',[]) if x not in ('KHR_materials_ior','KHR_materials_specular') or any(x in m.get('extensions',{}) for m in doc.get('materials',[]))]
json_chunk=json.dumps(doc,separators=(',',':'),ensure_ascii=False).encode('utf-8')
json_chunk+=b' '*((-len(json_chunk))%4)
rest=glb[20+json_len:]
patched=b'glTF'+struct.pack('<II',2,20+len(json_chunk)+len(rest))+struct.pack('<I4s',len(json_chunk),b'JSON')+json_chunk+rest
with open(model_path,'wb') as f: f.write(patched)

# Re-import the exported GLB in a clean file to validate the deliverable.
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=model_path)
check_meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
check_hair=[o for o in check_meshes if o.name.lower().startswith('chestnut hair')]
if len(check_meshes) < 5 or len(check_hair) != 4:
    raise RuntimeError('GLB round-trip failed: meshes=%s hair=%s' % ([o.name for o in check_meshes],[o.name for o in check_hair]))

# Save the final imported GLB material state into the editable project as well.
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
report={'blender':bpy.app.version_string,'hair_objects':len(check_hair),'total_meshes':len(check_meshes),'roundtrip':'passed','renders':'disabled','clearance_mm':clearance*1000,'fit':fit_report}
with open(os.path.join(out_dir,'hair-swap-report.json'),'w') as f: json.dump(report,f,indent=2)
print('HAIR_FIT_OK',json.dumps(report),flush=True)
