import numpy as np

def smoothstep(a,b,t):
    u=np.clip((t-a)/(b-a),0,1)
    return u*u*(3-2*u)

def bump(x,y,cx,cy,sx,sy):
    r2=((x-cx)/sx)**2+((y-cy)/sy)**2
    return np.exp(-.5*r2)*(1-smoothstep(6.25,9,r2))

def deform(p):
    # Canonical coordinates: x left/right, y up, z toward the face, metres.
    x,y,z=p.T; mid=-.0015
    dx=np.zeros(len(p));dy=dx.copy();dz=dx.copy()
    # Raise the mandibular angle and ease the lateral bony corner.
    for sign in (-1,1):
        angle=bump(x,y,mid+sign*.054,-.069,.013,.017)*bump(z,y,.043,-.069,.025,.030)
        dy+=.0036*angle
        dx-=sign*.00135*angle
        # Ease the lower mandibular corner without filling out the cheek.
        taper=bump(x,y,mid+sign*.036,-.085,.016,.014)*smoothstep(.055,.091,z)
        dx-=sign*.00055*taper
        dz-=.00032*taper
    chin=bump(x,y,mid,-.087,.020,.012)*smoothstep(.090,.110,z)
    dz-=.00105*chin
    dy+=.00050*bump(x,y,mid,-.099,.023,.009)*smoothstep(.074,.103,z)
    # Reduce prominent supraorbital planes and soften the glabella.
    for cx in (mid-.025,mid+.025):
        dz-=.00055*bump(x,y,cx,.017,.017,.008)*smoothstep(.090,.110,z)
    dz-=.00025*bump(x,y,mid,.015,.010,.010)*smoothstep(.108,.119,z)
    # A gentle dorsal curve: a shallow middle dip flowing into the lower bridge.
    dz-=.00070*bump(x,y,mid,-.009,.0055,.010)*smoothstep(.114,.125,z)
    dz+=.00024*bump(x,y,mid,-.025,.0055,.006)*smoothstep(.122,.133,z)
    # Compact the lobule and rotate its front gently down around the supratip.
    tip=bump(x,y,mid,-.038,.0095,.0075)*smoothstep(.125,.137,z)
    theta=np.deg2rad(5.0)
    dx-=.105*(x-mid)*tip
    dy+=((np.cos(theta)-1)*(y+.028)-np.sin(theta)*(z-.131)-.00045)*tip
    dz+=(np.sin(theta)*(y+.028)+(np.cos(theta)-1)*(z-.131)-.00035)*tip
    # Keep the alar-to-tip transition restrained.
    for sign in (-1,1):
        w=bump(x,y,mid+sign*.011,-.043,.0045,.005)*smoothstep(.119,.131,z)
        dz-=.00018*w
    # Bring the mouth corners inward, with a broad smooth blend into the skin.
    mouth=bump(x,y,mid,-.063,.050,.012)*smoothstep(.099,.115,z)
    dx-=.205*(x-mid)*mouth
    for sign in (-1,1):
        corner=bump(x,y,mid+sign*.022,-.063,.006,.004)*smoothstep(.104,.118,z)
        dy+=.00040*corner
        bow=bump(x,y,mid+sign*.006,-.0575,.0038,.003)*smoothstep(.117,.124,z)
        dy+=.00028*bow
    dy-=.00020*bump(x,y,mid,-.0565,.003,.003)*smoothstep(.118,.125,z)
    dz-=.00025*bump(x,y,mid,-.0575,.014,.004)*smoothstep(.116,.123,z)
    # Slightly round the lower lip edge without adding cheek volume.
    lower=bump(x,y,mid,-.070,.012,.004)*smoothstep(.115,.122,z)
    dy-=.00020*lower
    dz+=.00015*lower
    return p+np.column_stack((dx,dy,dz))

import bpy, os, sys, json, hashlib
from mathutils import Vector
from mathutils.bvhtree import BVHTree
SOURCE_SHA='f03664feaaa2a4e8d6a35cd1b2b1523d2626e48d42bc949ae5689a9d6931e774'
source,outdir=map(os.path.abspath,sys.argv[sys.argv.index('--')+1:])
os.makedirs(outdir,exist_ok=True)
assert hashlib.sha256(open(source,'rb').read()).hexdigest()==SOURCE_SHA
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=source)
bpy.context.view_layer.update()

def normalized(n):return n/np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-20)
def canonical(ob):
    v=np.empty(len(ob.data.vertices)*3);ob.data.vertices.foreach_get('co',v)
    M=np.array(ob.matrix_world,dtype=float)
    world=v.reshape(-1,3)@M[:3,:3].T+M[:3,3]
    return world[:,[0,2,1]]*np.array([1,1,-1]),M

def textures():
    out=[]
    for im in bpy.data.images:
        if im.size[0] and im.size[1] and im.type!='RENDER_RESULT':
            pix=np.empty(len(im.pixels),dtype=np.float32);im.pixels.foreach_get(pix)
            out.append((tuple(im.size),hashlib.sha256(pix.tobytes()).hexdigest()))
    return sorted(out)

def intersections():
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    face=next(o for o in meshes if 'Face_Mat' in o.name)
    def bvh(ob):
        ob.data.calc_loop_triangles()
        return BVHTree.FromPolygons([ob.matrix_world@v.co for v in ob.data.vertices],[tuple(t.vertices) for t in ob.data.loop_triangles],all_triangles=True)
    f=bvh(face)
    return {o.name:len(bvh(o).overlap(f)) for o in meshes if o.name.startswith('Chestnut hair')}

tex0=textures();overlap0=intersections()
report={'blender':bpy.app.version_string,'source_sha256':SOURCE_SHA,'renders':False,'objects':[],'hair_head_intersections_before':overlap0}
expected_tris=0
for ob in [o for o in bpy.context.scene.objects if o.type=='MESH']:
    mesh=ob.data;mesh.calc_loop_triangles()
    tris=np.array([t.vertices[:] for t in mesh.loop_triangles],dtype=np.int32);expected_tris+=len(tris)
    p,M=canonical(ob);A=M[:3,:3];q=deform(p)
    J=np.empty((len(p),3,3));eps=1e-5
    for axis in range(3):
        d=np.zeros_like(p);d[:,axis]=eps;J[:,:,axis]=(deform(p+d)-deform(p-d))/(2*eps)
    det=np.linalg.det(J);assert det.min()>.5
    loop_v=np.empty(len(mesh.loops),dtype=np.int32);mesh.loops.foreach_get('vertex_index',loop_v)
    normals=np.array([n.vector[:] for n in mesh.corner_normals],dtype=float)
    world_n=normals@np.linalg.inv(A)
    cn=normalized(world_n[:,[0,2,1]]*np.array([1,1,-1]))
    cn=normalized(np.linalg.solve(J[loop_v].transpose(0,2,1),cn[...,None])[...,0])
    local_n=normalized((cn[:,[0,2,1]]*np.array([1,-1,1]))@A)
    world_q=q[:,[0,2,1]]*np.array([1,-1,1])
    local=(world_q-M[:3,3])@np.linalg.inv(A).T
    assert np.isfinite(local).all() and np.isfinite(local_n).all()
    mesh.vertices.foreach_set('co',local.astype(np.float32).ravel());mesh.update()
    mesh.normals_split_custom_set(local_n.tolist())
    f0=np.cross(p[tris[:,1]]-p[tris[:,0]],p[tris[:,2]]-p[tris[:,0]])
    f1=np.cross(q[tris[:,1]]-q[tris[:,0]],q[tris[:,2]]-q[tris[:,0]])
    area0=np.linalg.norm(f0,axis=1);area1=np.linalg.norm(f1,axis=1);valid=area0>1e-15
    flipped=int(np.sum(np.sum(f0[valid]*f1[valid],axis=1)<0));degenerate=int(np.sum((area1<1e-15)&valid))
    assert flipped==0 and degenerate==0
    dist=np.linalg.norm(q-p,axis=1)
    rec={'name':ob.name,'vertices':len(p),'triangles':len(tris),'max_movement_mm':float(dist.max()*1000),'min_jacobian':float(det.min()),'flipped_triangles':flipped,'new_degenerate_triangles':degenerate}
    if 'Face_Mat' in ob.name:
        masks={'nose_tip':(abs(p[:,0]+.0015)<.008)&(p[:,1]>-.044)&(p[:,1]<-.034)&(p[:,2]>.136),'jaw_angle':(abs(abs(p[:,0]+.0015)-.054)<.006)&(abs(p[:,1]+.069)<.008)&(abs(p[:,2]-.043)<.02)}
        rec['region_average_shift_mm']={name:((q[m]-p[m]).mean(0)*1000).tolist() for name,m in masks.items()}
        corners=(abs(abs(p[:,0]+.0015)-.023)<.003)&(abs(p[:,1]+.063)<.005)&(p[:,2]>.11)
        rec['mouth_corner_average_inward_mm']=float((abs(p[corners,0]+.0015)-abs(q[corners,0]+.0015)).mean()*1000)
    report['objects'].append(rec)
    print('REFINE_OBJECT',json.dumps(rec),flush=True)

bpy.context.view_layer.update()
assert textures()==tex0
report['hair_head_intersections_after']=intersections()
assert sum(report['hair_head_intersections_after'].values())<=sum(overlap0.values())
bpy.ops.file.pack_all()
blend_path=os.path.join(outdir,'head_reference_refined.blend');glb_path=os.path.join(outdir,'head_reference_refined.glb')
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
bpy.ops.export_scene.gltf(filepath=glb_path,export_format='GLB',export_yup=True,export_normals=True,export_texcoords=True,export_materials='EXPORT',export_animations=False)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb_path)
bpy.context.view_layer.update()
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
actual_tris=0
for ob in meshes:
    ob.data.calc_loop_triangles();actual_tris+=len(ob.data.loop_triangles)
    p,_=canonical(ob);assert np.isfinite(p).all()
assert len(meshes)==9 and actual_tris==expected_tris
assert textures()==tex0
round_overlap=intersections();assert sum(round_overlap.values())==0
report['validation']={'glb_reimport':'passed','meshes':len(meshes),'triangles':actual_tris,'textures_unchanged':True,'hair_head_intersections':sum(round_overlap.values()),'renders_generated':0}
report['output_sha256']=hashlib.sha256(open(glb_path,'rb').read()).hexdigest()
with open(os.path.join(outdir,'refinement-report.json'),'w') as f:json.dump(report,f,indent=2)
print('FACE_REFINEMENT_OK',json.dumps(report['validation']),flush=True)
