import numpy as np

MID = -.0015

def smooth(a,b,x):
    t=np.clip((x-a)/(b-a),0,1)
    return t*t*(3-2*t)

def eye_field(p):
    x,y,z=p.T
    a=np.abs(x-MID)
    # Lift the upper lid over the pupil; leave the lower lid and canthi fixed.
    w=np.exp(-.5*((a-.028)/.0074)**2)
    w*=smooth(.014,.020,a)*(1-smooth(.038,.044,a))
    w*=smooth(.0019,.0047,y)*(1-smooth(.010,.019,y))
    w*=smooth(.077,.098,z)
    q=p.copy();q[:,1]+=.00095*w;q[:,2]+=.00006*w
    return q

def hair_field(p):
    x,y,z=p.T
    # Front roots and front sweep descend; crown, back, and lower lengths fade out.
    w=np.exp(-.5*((x-MID)/.050)**2)
    w*=smooth(.025,.055,y)*(1-smooth(.100,.150,y))
    w*=smooth(.035,.075,z)
    q=p.copy();q[:,1]-=.008*w;q[:,2]+=.003*w
    return q

def brow_radius(a):
    return a-.0075*smooth(.035,.059,a)

def brow_line(a):
    # metres; very restrained arch, highest at x = 37 mm from centre.
    knots=np.array([.009,.021,.028,.037,.052])
    values=np.array([.0180,.0178,.0180,.0192,.0179])
    slopes=np.array([-.012,0,.065,0,-.035])
    i=np.clip(np.searchsorted(knots,a)-1,0,len(knots)-2)
    h=knots[i+1]-knots[i];t=np.clip((a-knots[i])/h,0,1)
    return (2*t**3-3*t*t+1)*values[i]+(t**3-2*t*t+t)*h*slopes[i]+(-2*t**3+3*t*t)*values[i+1]+(t**3-t*t)*h*slopes[i+1]

import bpy, os, sys, json, hashlib, struct
from mathutils import Vector
from mathutils.bvhtree import BVHTree

SOURCE_SHA='74553755589a3d3023769097e3423ba3dc54c293ee5856a4c2dfe9498fd50573'
source,outdir=map(os.path.abspath,sys.argv[sys.argv.index('--')+1:])
assert hashlib.sha256(open(source,'rb').read()).hexdigest()==SOURCE_SHA
os.makedirs(outdir,exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=source)
bpy.context.view_layer.update()

def norm(n): return n/np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-20)
def canonical(ob):
    a=np.empty(len(ob.data.vertices)*3);ob.data.vertices.foreach_get('co',a)
    M=np.array(ob.matrix_world,dtype=float)
    p=a.reshape(-1,3)@M[:3,:3].T+M[:3,3]
    return p[:,[0,2,1]]*np.array([1,1,-1]),M
def triangles(mesh):
    mesh.calc_loop_triangles()
    return np.array([t.vertices[:] for t in mesh.loop_triangles],dtype=np.int32)
def tree(p,t): return BVHTree.FromPolygons(p.tolist(),t.tolist(),all_triangles=True)
def texhash():
    out=[]
    for im in bpy.data.images:
        if im.size[0] and im.size[1] and im.type!='RENDER_RESULT':
            pix=np.empty(len(im.pixels),dtype=np.float32);im.pixels.foreach_get(pix)
            out.append((tuple(im.size),hashlib.sha256(pix.tobytes()).hexdigest()))
    return sorted(out)
def geometry_stats(p,q,t):
    n0=np.cross(p[t[:,1]]-p[t[:,0]],p[t[:,2]]-p[t[:,0]])
    n1=np.cross(q[t[:,1]]-q[t[:,0]],q[t[:,2]]-q[t[:,0]])
    valid=np.linalg.norm(n0,axis=1)>1e-15
    flips=int(((n0[valid]*n1[valid]).sum(1)<-1e-28).sum())
    degenerate=int((np.linalg.norm(n1[valid],axis=1)<1e-15).sum())
    assert flips==0 and degenerate==0,(flips,degenerate)
    return {'max_movement_mm':float(np.linalg.norm(q-p,axis=1).max()*1000),'flipped_triangles':flips,'new_degenerate_triangles':degenerate}
def apply_field(ob,fn):
    p,M=canonical(ob);q=fn(p);mesh=ob.data;t=triangles(mesh)
    rec=geometry_stats(p,q,t)
    J=np.empty((len(p),3,3));eps=1e-5
    for a in range(3):
        d=np.zeros_like(p);d[:,a]=eps;J[:,:,a]=(fn(p+d)-fn(p-d))/(2*eps)
    rec['min_jacobian']=float(np.linalg.det(J).min());assert rec['min_jacobian']>.45
    A=M[:3,:3];lv=np.empty(len(mesh.loops),dtype=np.int32);mesh.loops.foreach_get('vertex_index',lv)
    normals=np.array([n.vector[:] for n in mesh.corner_normals],dtype=float)
    cn=norm((normals@np.linalg.inv(A))[:,[0,2,1]]*np.array([1,1,-1]))
    cn=norm(np.linalg.solve(J[lv].transpose(0,2,1),cn[...,None])[...,0])
    newn=norm((cn[:,[0,2,1]]*np.array([1,-1,1]))@A)
    world=q[:,[0,2,1]]*np.array([1,-1,1]);local=(world-M[:3,3])@np.linalg.inv(A).T
    assert np.isfinite(local).all() and np.isfinite(newn).all()
    mesh.vertices.foreach_set('co',local.astype(np.float32).ravel());mesh.update();mesh.normals_split_custom_set(newn.tolist())
    return rec
def components(mesh):
    parent=np.arange(len(mesh.vertices))
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    for e in mesh.edges:
        a,b=map(root,e.vertices);parent[b]=a
    _,label=np.unique([root(i) for i in range(len(parent))],return_inverse=True)
    return label

meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
face=next(o for o in meshes if 'Face_Mat' in o.name)
brows=next(o for o in meshes if 'eyebrow' in o.name)
hair=[o for o in meshes if o.name.startswith('Chestnut hair')]
tex0=texhash();expected_tris=sum(len(triangles(o.data)) for o in meshes)
fp0,_=canonical(face);ft=triangles(face.data);face0=tree(fp0,ft)
report={'blender':bpy.app.version_string,'source_sha256':SOURCE_SHA,'renders_generated':0,'objects':[]}
report['hair_head_intersections_before']={o.name:len(tree(canonical(o)[0],triangles(o.data)).overlap(face0)) for o in hair}
assert sum(report['hair_head_intersections_before'].values())==0

# Upper eyelid, attached lash roots, and tearline move together.
for ob in meshes:
    if 'Face_Mat' in ob.name or 'eyelash' in ob.name or 'Tearline' in ob.name:
        rec=apply_field(ob,eye_field);rec['name']=ob.name;report['objects'].append(rec)
        print('UPPER_LID',json.dumps(rec),flush=True)
fp,_=canonical(face);surface=tree(fp,ft)
def surface_z(x,y):
    hit,n,idx,d=surface.ray_cast(Vector((float(x),float(y),.4)),Vector((0,0,-1)),.7)
    return None if hit is None else hit.z

# Keep every existing strand, preserving its geometry and natural irregularity.
p,M=canonical(brows);mesh=brows.data;labels=components(mesh)
count=int(labels.max()+1);assert count==2064
groups=[np.flatnonzero(labels==k) for k in range(count)]
centers=np.array([p[g].mean(0) for g in groups]);r=np.abs(centers[:,0]-MID)
fits={}
for side in [-1,1]:
    m=np.sign(centers[:,0]-MID)==side
    fits[side]=np.polynomial.Polynomial.fit(r[m],centers[m,1],4).convert()
q=p.copy();colors=np.ones((len(p),4),dtype=np.float32);newcenters=[];root_clearances=[]
for k,g in enumerate(groups):
    c=centers[k];side=-1 if c[0]<MID else 1;a=r[k]
    oldline=float(fits[side](a));radius=float(brow_radius(a));desired=float(brow_line(radius))
    residual=c[1]-oldline
    nc=c.copy();nc[0]=MID+side*radius;nc[1]=desired+residual
    oz=surface_z(c[0],c[1]);nz=surface_z(nc[0],nc[1]);assert oz is not None and nz is not None
    nc[2]=nz+max(c[2]-oz,.00022)
    q[g]=p[g]+(nc-c)
    # Maintain front-surface clearance after the lateral move.
    required=0.0
    for v in q[g]:
        zz=surface_z(v[0],v[1])
        if zz is not None:required=max(required,zz+.00008-v[2])
    q[g,2]+=required;newcenters.append(q[g].mean(0))
    root_clearances.append(float(q[g,2].min()))
    edge=float(smooth(.00065,.00215,abs(residual)))
    root=float(1-smooth(.011,.019,radius))
    blend=max(edge*.80,root*.45)
    core=np.array([.035,.026,.020]);rim=np.array([.080,.061,.047])
    variation=1+.075*np.sin(k*2.399963)
    # Continuous tint along each strand, including a slightly softer tip.
    tip=(p[g,1]-p[g,1].min())/max(float(np.ptp(p[g,1])),1e-6)
    shade=(core*(1-blend)+rim*blend)*variation
    colors[g,:3]=shade[None,:]*(1+.10*tip[:,None])
rec=geometry_stats(p,q,triangles(mesh));world=q[:,[0,2,1]]*np.array([1,-1,1]);local=(world-M[:3,3])@np.linalg.inv(M[:3,:3]).T
oldnorm=np.array([n.vector[:] for n in mesh.corner_normals]);mesh.vertices.foreach_set('co',local.astype(np.float32).ravel());mesh.update();mesh.normals_split_custom_set(oldnorm.tolist())
color=mesh.color_attributes.new(name='BrowSoftTint',type='FLOAT_COLOR',domain='POINT');color.data.foreach_set('color',colors.ravel());mesh.color_attributes.active_color=color
mat=mesh.materials[0];mat.name='Soft neutral brown brows | full strand density';mat.use_nodes=True
bs=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
for link in list(bs.inputs['Base Color'].links):mat.node_tree.links.remove(link)
col=mat.node_tree.nodes.new('ShaderNodeVertexColor');col.layer_name=color.name;mat.node_tree.links.new(col.outputs['Color'],bs.inputs['Base Color'])
bs.inputs['Alpha'].default_value=1;bs.inputs['Roughness'].default_value=.86
mat.diffuse_color=(.035,.026,.020,1)
rec.update({'name':brows.name,'strands_before':count,'strands_after':count,'density_reduced':False,'alpha_min':float(colors[:,3].min()),'color_linear_min':colors[:,:3].min(0).tolist(),'color_linear_max':colors[:,:3].max(0).tolist(),'edge_transition':'continuous per-strand vertex tint, opaque'})
knots=np.array([.012,.021,.028,.037,.051]);rec['target_centerline_x_y_mm']=np.column_stack([knots,brow_line(knots)]).tolist()
rec['target_centerline_x_y_mm']=(np.column_stack([knots,brow_line(knots)])*1000).tolist()
newcenters=np.array(newcenters);rec['tail_radius_before_mm']=float(r.max()*1000);rec['tail_radius_after_mm']=float(abs(newcenters[:,0]-MID).max()*1000)
report['objects'].append(rec);print('BROWS',json.dumps(rec),flush=True)

# Lower only the front hairline; select the smallest outward correction that
# keeps both hair vertices and triangle interiors clear of the head.
for ob in hair:
    p,_=canonical(ob);t=triangles(ob.data);base=hair_field(p);weight=(p[:,1]-base[:,1])/.008
    affected=np.flatnonzero((weight>.03)&(p[:,1]>.025))
    success=False
    for attempt in range(7):
        extra=.001*attempt
        def field(v):
            q=hair_field(v);w=(v[:,1]-q[:,1])/.008;q[:,2]+=extra*w;return q
        q=field(p);inter=len(tree(q,t).overlap(surface));inside=0
        for v in q[affected]:
            zz=surface_z(v[0],v[1])
            if zz is not None and v[2]<zz+.00015:inside+=1
        if inter==0 and inside==0:success=True;break
    assert success,(ob.name,inter,inside)
    rec=apply_field(ob,field);rec.update({'name':ob.name,'extra_front_clearance_mm':extra*1000,'hair_head_intersections':inter,'front_inside_vertices':inside,'max_hairline_lower_mm':float((p[:,1]-q[:,1]).max()*1000)})
    report['objects'].append(rec);print('HAIRLINE',json.dumps(rec),flush=True)

assert texhash()==tex0
bpy.context.view_layer.update();bpy.ops.file.pack_all()
blend=os.path.join(outdir,'head_soft_brows_eyes.blend');glb=os.path.join(outdir,'head_soft_brows_eyes.glb')
bpy.ops.wm.save_as_mainfile(filepath=blend)
bpy.ops.export_scene.gltf(filepath=glb,export_format='GLB',export_yup=True,export_normals=True,export_texcoords=True,export_materials='EXPORT',export_animations=False)
raw=open(glb,'rb').read();jl=struct.unpack_from('<I',raw,12)[0];doc=json.loads(raw[20:20+jl])
brow_prims=next(m for m in doc['meshes'] if 'eyebrow' in m.get('name','').lower())['primitives']
assert all('COLOR_0' in x['attributes'] for x in brow_prims),'Brow tint did not survive GLB export'
bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=glb);bpy.context.view_layer.update()
out=[o for o in bpy.context.scene.objects if o.type=='MESH'];assert len(out)==9
assert sum(len(triangles(o.data)) for o in out)==expected_tris
assert texhash()==tex0
face=next(o for o in out if 'Face_Mat' in o.name);f=tree(canonical(face)[0],triangles(face.data))
inter={o.name:len(tree(canonical(o)[0],triangles(o.data)).overlap(f)) for o in out if o.name.startswith('Chestnut hair')}
assert sum(inter.values())==0
brow=next(o for o in out if 'eyebrow' in o.name);assert components(brow.data).max()+1==count
for o in out:assert np.isfinite(canonical(o)[0]).all()
report['validation']={'glb_reimport':'passed','meshes':len(out),'triangles':expected_tris,'textures_unchanged':True,'eyebrow_strands':count,'vertex_colors_exported':True,'hair_head_intersections':inter,'renders_generated':0}
report['output_sha256']=hashlib.sha256(raw).hexdigest()
with open(os.path.join(outdir,'soft-brows-eyes-report.json'),'w') as f:json.dump(report,f,indent=2)
print('SOFT_BROWS_EYES_OK',json.dumps(report['validation']),flush=True)
