"""Final localized nasal, philtrum and jawline correction. No cameras or rendering."""
import bpy
import hashlib
import json
import os
import sys
import numpy as np
from mathutils.kdtree import KDTree

SOURCE_SHA256 = '833d0884fd08b641b241fb45857388d80dd856f421ad8a87c9e5a2083983f8a8'

def smoothstep(a, b, t):
    u = np.clip((t-a)/(b-a), 0, 1)
    return u*u*(3-2*u)

def bump(x, y, cx, cy, sx, sy):
    r2 = ((x-cx)/sx)**2 + ((y-cy)/sy)**2
    return np.exp(-.5*r2)*(1-smoothstep(6.25, 9, r2))

def deform(p):
    # glTF axes: X left/right, Y up, Z forward, metres.
    x,y,z=p.T
    mid=-.0015
    dx=np.zeros(len(p));dy=dx.copy();dz=dx.copy()
    nasal=smoothstep(.119,.131,z)*(1-smoothstep(-.028,-.023,y))
    tip=bump(x,y,mid,-.0375,.0095,.0075)*nasal
    # Retract the lobule, give it a slight downward inclination, round shoulders.
    dx+=.035*(x-mid)*tip
    dy-=.00075*tip
    dz-=.00155*tip
    # Blend back to the alar base without reducing nostril apertures abruptly.
    base=bump(x,y,mid,-.047,.011,.005)*smoothstep(.112,.124,z)
    base*=smoothstep(-.057,-.053,y)
    dz-=.00055*base
    philtrum=bump(x,y,mid,-.0515,.0065,.0038)*smoothstep(.114,.122,z)
    philtrum*=smoothstep(-.057,-.054,y)
    dz-=.00065*philtrum
    return p+np.column_stack((dx,dy,dz))

def normalized(n):
    return n/np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-20)

def surface_normals(p, tris):
    n = np.zeros_like(p)
    f = np.cross(p[tris[:,1]]-p[tris[:,0]], p[tris[:,2]]-p[tris[:,0]])
    for k in range(3): np.add.at(n,tris[:,k],f)
    return normalized(n)

def smooth_jawline(p, tris):
    # Work on shared position groups so the UV seam remains closed.
    key, inv = np.unique(np.round(p,7),axis=0,return_inverse=True)
    n = len(key)
    u = np.zeros((n,3)); np.add.at(u,inv,p)
    u /= np.bincount(inv)[:,None]
    ti = inv[tris]
    edges = np.sort(np.concatenate((ti[:,[0,1]],ti[:,[1,2]],ti[:,[2,0]])),axis=1)
    edges, counts = np.unique(edges,axis=0,return_counts=True)
    boundary = np.unique(edges[counts==1])
    kd = KDTree(len(boundary))
    for i, v in enumerate(boundary): kd.insert(tuple(u[v]),i)
    kd.balance()
    x,y,z = u.T
    jaw_height=-.045-.55*z
    distance_from_band=y-jaw_height
    w=np.exp(-.5*(distance_from_band/.013)**2)
    w*=1-smoothstep(.028,.038,np.abs(distance_from_band))
    w*=smoothstep(.017,.032,np.abs(x+.0015))
    w*=smoothstep(-.005,.015,z)*(1-smoothstep(.09,.112,z))
    w*=1-smoothstep(-.046,-.035,y)
    ids = np.flatnonzero(w>0)
    distance = np.array([kd.find(tuple(u[i]))[2] for i in ids])
    w[ids] *= smoothstep(.001,.004,distance)
    a,b = edges.T
    degree = np.bincount(edges.ravel(),minlength=n)
    q = u.copy()
    for _ in range(60):
        sums = np.zeros_like(q)
        np.add.at(sums,a,q[b]); np.add.at(sums,b,q[a])
        q += .35*w[:,None]*(sums/np.maximum(degree[:,None],1)-q)
    delta = q-u
    length = np.linalg.norm(delta,axis=1)
    delta *= np.minimum(1,.00080/np.maximum(length,1e-20))[:,None]
    q = u+delta
    n0 = surface_normals(u,ti); n1 = surface_normals(q,ti)
    # Track geometric normal rotations without removing the original smooth normals.
    axis = np.cross(n0,n1); cosine = np.sum(n0*n1,axis=1)
    local_change = np.linalg.norm(delta,axis=1)
    before_sum = np.zeros_like(u); after_sum = np.zeros_like(u)
    np.add.at(before_sum,a,u[b]);np.add.at(before_sum,b,u[a])
    np.add.at(after_sum,a,q[b]);np.add.at(after_sum,b,q[a])
    lap0 = np.linalg.norm(before_sum/np.maximum(degree[:,None],1)-u,axis=1)
    lap1 = np.linalg.norm(after_sum/np.maximum(degree[:,None],1)-q,axis=1)
    stat = {'max_smoothing_mm':float(local_change.max()*1000),
            'vertices_smoothed_over_0_01mm':int(np.sum(local_change>1e-5)),
            'weighted_laplacian_before_mm':float(np.sum(w*lap0)/w.sum()*1000),
            'weighted_laplacian_after_mm':float(np.sum(w*lap1)/w.sum()*1000)}
    target=n1.copy()
    for _ in range(3):
        sums=np.zeros_like(target)
        np.add.at(sums,a,target[b]);np.add.at(sums,b,target[a])
        target=normalized(.5*target+.5*sums/np.maximum(degree[:,None],1))
    return p+delta[inv], axis[inv], cosine[inv], target[inv], .85*w[inv], stat

def canonical(ob):
    mesh = ob.data
    co = np.empty(len(mesh.vertices)*3); mesh.vertices.foreach_get('co',co)
    M = np.array(ob.matrix_world,dtype=float)
    world = co.reshape(-1,3)@M[:3,:3].T+M[:3,3]
    return world[:,[0,2,1]]*np.array([1,1,-1]),M

def texture_hashes():
    result = []
    for im in bpy.data.images:
        if im.size[0] and im.size[1] and im.type != 'RENDER_RESULT':
            data = np.empty(len(im.pixels),dtype=np.float32);im.pixels.foreach_get(data)
            result.append({'size':list(im.size),'pixel_sha256':hashlib.sha256(data.tobytes()).hexdigest()})
    return sorted(result,key=lambda item:(item['size'],item['pixel_sha256']))

args = sys.argv[sys.argv.index('--')+1:]
source, outdir = map(os.path.abspath,args)
os.makedirs(outdir,exist_ok=True)
assert hashlib.sha256(open(source,'rb').read()).hexdigest() == SOURCE_SHA256
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=source)
bpy.context.view_layer.update()
textures_before = texture_hashes()
objects = [o for o in bpy.context.scene.objects if o.type=='MESH']
report = {'blender_version':bpy.app.version_string,'source_sha256':SOURCE_SHA256,
          'rendering_performed':False,'objects':[],'textures_before':textures_before}
expected_triangles = 0
for ob in objects:
    mesh = ob.data
    mesh.calc_loop_triangles()
    tris = np.array([t.vertices[:] for t in mesh.loop_triangles],dtype=np.int32)
    expected_triangles += len(tris)
    p,M = canonical(ob); A = M[:3,:3]
    loop_v = np.empty(len(mesh.loops),dtype=np.int32);mesh.loops.foreach_get('vertex_index',loop_v)
    old_normals = np.array([n.vector[:] for n in mesh.corner_normals],dtype=float)
    world_n = old_normals@np.linalg.inv(A)
    gltf_n = normalized(world_n[:,[0,2,1]]*np.array([1,1,-1]))
    base = p.copy()
    rec = {'name':ob.name,'triangles':len(tris)}
    if 'Face_Mat' in ob.name:
        base,axis,cosine,jaw_normals,jaw_normal_weight,rec['jawline_smoothing'] = smooth_jawline(p,tris)
        v = axis[loop_v];c = cosine[loop_v,None]
        gltf_n += np.cross(v,gltf_n)+np.cross(v,np.cross(v,gltf_n))/np.maximum(1+c,1e-12)
        weight=jaw_normal_weight[loop_v,None]
        gltf_n=normalized(gltf_n*(1-weight)+jaw_normals[loop_v]*weight)
    after = deform(base)
    J = np.empty((len(p),3,3));eps=1e-5
    for axis_i in range(3):
        d=np.zeros_like(base);d[:,axis_i]=eps
        J[:,:,axis_i]=(deform(base+d)-deform(base-d))/(2*eps)
    rec['min_jacobian_det'] = float(np.linalg.det(J).min())
    assert rec['min_jacobian_det']>.5
    gltf_n = normalized(np.linalg.solve(J[loop_v].transpose(0,2,1),gltf_n[...,None])[...,0])
    new_world_n = gltf_n[:,[0,2,1]]*np.array([1,-1,1])
    local_n = normalized(new_world_n@A)
    world_new = after[:,[0,2,1]]*np.array([1,-1,1])
    local = (world_new-M[:3,3])@np.linalg.inv(A).T
    assert np.isfinite(local).all() and np.isfinite(local_n).all()
    mesh.vertices.foreach_set('co',local.astype(np.float32).ravel());mesh.update()
    mesh.normals_split_custom_set(local_n.tolist())
    f0=np.cross(p[tris[:,1]]-p[tris[:,0]],p[tris[:,2]]-p[tris[:,0]])
    f1=np.cross(after[tris[:,1]]-after[tris[:,0]],after[tris[:,2]]-after[tris[:,0]])
    area0=np.linalg.norm(f0,axis=1);area1=np.linalg.norm(f1,axis=1);valid=area0>1e-15
    rec['flipped_triangles']=int(np.sum(np.sum(f0[valid]*f1[valid],axis=1)<0))
    rec['new_degenerate_triangles']=int(np.sum((area1<1e-15)&valid))
    assert rec['flipped_triangles']==0 and rec['new_degenerate_triangles']==0
    dist=np.linalg.norm(after-p,axis=1)
    rec['max_displacement_mm']=float(dist.max()*1000)
    if 'Face_Mat' in ob.name:
        bridge=(abs(p[:,0]+.0015)<.006)&(p[:,1]>-.022)&(p[:,1]<.014)&(p[:,2]>.12)
        rec['upper_nasal_bridge_max_change_mm']=float(dist[bridge].max()*1000)
        nose=(abs(p[:,0]+.0015)<.025)&(p[:,1]<-.025)&(p[:,1]>-.055)&(p[:,2]>.12)
        rec['nose_max_displacement_mm']=float(dist[nose].max()*1000)
        assert rec['upper_nasal_bridge_max_change_mm']<.025
        region=(abs(p[:,0]+.0015)<.011)&(p[:,1]>-.045)&(p[:,1]<-.030)&(p[:,2]>.135)
        rec['tip_average_shift_mm']=((after[region]-p[region]).mean(axis=0)*1000).tolist()
        phil=(abs(p[:,0]+.0015)<.006)&(p[:,1]>-.055)&(p[:,1]<-.048)&(p[:,2]>.117)
        rec['philtrum_average_retraction_mm']=float((p[phil,2]-after[phil,2]).mean()*1000)
        eyes=(abs(p[:,0]+.0015)>.012)&(p[:,1]>-.018)&(p[:,1]<.024)
        rec['eye_region_max_change_mm']=float(dist[eyes].max()*1000)
        assert rec['eye_region_max_change_mm']<1e-8
    report['objects'].append(rec)
    print('CORRECTION_METRIC',json.dumps(rec),flush=True)

assert textures_before==texture_hashes()
blend_path=os.path.join(outdir,'head_corrected.blend')
glb_path=os.path.join(outdir,'head_corrected.glb')
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
bpy.ops.export_scene.gltf(filepath=glb_path,export_format='GLB',export_yup=True,
                         export_normals=True,export_texcoords=True,export_materials='EXPORT',
                         export_animations=False)
# Real export/import validation in the same Blender process.
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb_path)
loaded=[o for o in bpy.context.scene.objects if o.type=='MESH']
actual_triangles=0
for ob in loaded:
    ob.data.calc_loop_triangles();actual_triangles+=len(ob.data.loop_triangles)
    co=np.empty(len(ob.data.vertices)*3);ob.data.vertices.foreach_get('co',co)
    assert np.isfinite(co).all()
assert len(loaded)==5 and actual_triangles==expected_triangles
assert len(bpy.data.materials)==5
assert texture_hashes()==textures_before
report['validation']={'mesh_objects':len(loaded),'materials':len(bpy.data.materials),
                      'triangles':actual_triangles,'textures_identical':True,'glb_reimport':'passed'}
report['output_sha256']=hashlib.sha256(open(glb_path,'rb').read()).hexdigest()
with open(os.path.join(outdir,'correction-report.json'),'w') as f:json.dump(report,f,indent=2)
print('HEAD_CORRECTION_SUCCESS',json.dumps(report['validation']),flush=True)
