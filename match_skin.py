import bpy,numpy as np,os,json,struct
bpy.ops.wm.open_mainfile(filepath=os.path.abspath('prior/jill_head_hair_replaced.blend'))
head=next(o for o in bpy.context.scene.objects if o.type=='MESH' and o.name.startswith('Replacement_') and 'Face_Mat' in o.name)
neck=bpy.data.objects.get('Jill_original_neck_connector')
mat=head.data.materials[0];refmat=neck.data.materials[0]
bs=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
# Find image nodes feeding the base colour chain.
def baseimage(m):
 p=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
 def walk(n):
  if n.type=='TEX_IMAGE':return n.image
  for inp in n.inputs:
   for link in inp.links:
    im=walk(link.from_node)
    if im:return im
 for l in p.inputs['Base Color'].links:
  im=walk(l.from_node)
  if im:return im
 raise RuntimeError('base image absent')
im=baseimage(mat);ref=baseimage(refmat)
def pixels(im):
 a=np.empty(len(im.pixels),np.float32);im.pixels.foreach_get(a);return a.reshape(im.size[1],im.size[0],4)
a=pixels(im);r=pixels(ref)
# Blender stores image pixels in linear light. Compute correction from corresponding neck UVs.
def srgb(x):return np.where(x<=.0031308,12.92*x,1.055*np.maximum(x,0)**(1/2.4)-.055)
def linear(x):return np.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)
c=srgb(a[:,:,:3]);rr=srgb(r[:,:,:3]);h,w=c.shape[:2];rh,rw=rr.shape[:2]
# Pixel array is bottom-up. This rectangular patch is lower neck in both UV layouts.
y,x=np.mgrid[0:h,0:w];u=x/w;v=1-y/h
sample=(u>.36)&(u<.64)&(v>.55)&(v<.66)
rx=np.clip((u*rw).astype(int),0,rw-1);ry=np.clip(((1-v)*rh).astype(int),0,rh-1);target=rr[ry,rx]
valid=sample&(c[:,:,0]>.4)&(c[:,:,0]>c[:,:,2]*1.12)&(target[:,:,0]>.4)
delta=np.median(target[valid],axis=0)-np.median(c[valid],axis=0)
delta=np.clip(delta,[-.03,-.03,-.03],[.12,.18,.18])
# Skin mask: preserve black background, deep eye shading, red lip pigment and mouth interior.
light=np.clip((c[:,:,0]-.22)/.26,0,1)
redness=c[:,:,0]-c[:,:,1]
lip=1-np.clip((redness-.24)/.12,0,1)
mask=light*lip
corrected=np.clip(c+mask[:,:,None]*delta,0,1)
a[:,:,:3]=linear(corrected)
os.makedirs('skin-output',exist_ok=True)
new=bpy.data.images.new('Head skin matched to Jill body',width=w,height=h,alpha=True);new.colorspace_settings.name='sRGB';new.pixels.foreach_set(a.ravel());new.filepath_raw=os.path.abspath('skin-output/head_skin_matched.png');new.file_format='PNG';new.save();new.pack()
for n in mat.node_tree.nodes:
 if n.type=='TEX_IMAGE' and n.image==im:n.image=new
# Remove the tinted constant multiplier; retain vertex colour and image connections.
for n in mat.node_tree.nodes:
 if n.type=='MIX' and n.data_type=='RGBA':
  for inp in n.inputs:
   if inp.type=='RGBA' and not inp.is_linked:
    val=tuple(inp.default_value)
    if any(abs(val[i]-t)<.001 for i,t in enumerate([.94,.89,.86])):inp.default_value=(1,1,1,1)
 if n.type=='MIX_RGB':
  for inp in n.inputs:
   if inp.type=='RGBA' and not inp.is_linked:inp.default_value=(1,1,1,1)
# Preserve natural roughness and facial geometry.
mat.name='Head skin | matched to Jill body'
out=os.path.abspath('skin-output/jill_skin_matched.glb')
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath('skin-output/jill_skin_matched.blend'))
bpy.ops.export_scene.gltf(filepath=out,export_format='GLB',export_animations=False,export_all_influences=True)
b=open(out,'rb').read();assert struct.unpack_from('<I',b,8)[0]==len(b)
bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=out)
assert any(o.type=='MESH' and o.name.startswith('Replacement_') and 'Face_Mat' in o.name for o in bpy.context.scene.objects)
assert any(o.type=='ARMATURE' for o in bpy.context.scene.objects)
report={'blender':bpy.app.version_string,'srgb_neck_delta':delta.tolist(),'neck_before':np.median(c[valid],axis=0).tolist(),'neck_target':np.median(target[valid],axis=0).tolist(),'neck_after':np.median(corrected[valid],axis=0).tolist(),'roundtrip':'PASS','bytes':len(b)}
open('skin-output/validation.json','w').write(json.dumps(report,indent=2));print('SKIN_MATCH_VALIDATED',report)
