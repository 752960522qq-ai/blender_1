import numpy as np

def densify(points,triangles):
    parent=np.arange(len(points))
    def root(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]];x=parent[x]
        return x
    for a,b,c in triangles:
        ra=root(a);rb=root(b);rc=root(c)
        parent[rb]=ra;parent[rc]=ra
    ids=np.array([root(i) for i in range(len(points))]);groups=[np.flatnonzero(ids==k) for k in np.unique(ids)]
    assert all(len(g)==30 for g in groups),'Unexpected eyebrow strand topology'
    strands=np.array([points[g].reshape(6,5,3) for g in groups])
    centers=strands.mean(2);radial=strands-centers[:,:,None,:]
    tang=centers[:,-1]-centers[:,0];tang/=np.linalg.norm(tang,axis=1)[:,None]
    xy=tang[:,:2];xy/=np.linalg.norm(xy,axis=1)[:,None]
    across=np.stack([-xy[:,1],xy[:,0]],axis=1)
    mids=centers.mean(1);pairs=set()
    for i in range(len(groups)):
        d=mids-mids[i]
        perp=np.abs(d[:,:2]@across[i]);along=np.abs(d[:,:2]@xy[i])
        mask=(mids[:,0]*mids[i,0]>0)&(tang@tang[i]>.90)&(perp>.00013)&(perp<.00070)&(along<.0014)&(np.linalg.norm(d,axis=1)<.0018)
        mask[i]=False
        cand=np.flatnonzero(mask)
        if len(cand):
            score=np.abs(perp[cand]-.00038)+.35*along[cand]
            j=int(cand[np.argmin(score)]);pairs.add(tuple(sorted((i,j))))
    newpoints=points.copy()
    for i,g in enumerate(groups):
        newpoints[g]=(centers[i,:,None,:]+1.28*radial[i]).reshape(-1,3)
    # All tubes share the same 6-ring, 5-sided topology. Interpolate complete
    # neighboring strands to add density along the existing flow and outline.
    first=groups[0];lookup={int(v):i for i,v in enumerate(first)}
    own=np.isin(triangles[:,0],first)
    template=np.array([[lookup[int(v)] for v in t] for t in triangles[own]])
    assert len(template)==50
    added=[];faces=[triangles]
    for a,b in sorted(pairs):
        center=(centers[a]+centers[b])*.5
        cross=(radial[a]+radial[b])*.5*1.12
        q=(center[:,None,:]+cross).reshape(-1,3)
        added.append(q)
        faces.append(template+len(points)+(len(added)-1)*30)
    out=np.concatenate([newpoints]+added)
    ft=np.concatenate(faces)
    area=np.linalg.norm(np.cross(out[ft[:,1]]-out[ft[:,0]],out[ft[:,2]]-out[ft[:,0]]),axis=1)
    assert np.isfinite(out).all() and area.min()>1e-14
    normals0=np.cross(points[triangles[:,1]]-points[triangles[:,0]],points[triangles[:,2]]-points[triangles[:,0]])
    normals1=np.cross(newpoints[triangles[:,1]]-newpoints[triangles[:,0]],newpoints[triangles[:,2]]-newpoints[triangles[:,0]])
    assert np.all(np.sum(normals0*normals1,axis=1)>0)
    return out,ft,{'original_strands':len(groups),'added_strands':len(added),'final_strands':len(groups)+len(added),'original_hair_radius_scale':1.28,'max_original_vertex_shift_mm':float(np.linalg.norm(newpoints-points,axis=1).max()*1000),'triangles_before':len(triangles),'triangles_after':len(ft),'min_triangle_double_area':float(area.min())}

