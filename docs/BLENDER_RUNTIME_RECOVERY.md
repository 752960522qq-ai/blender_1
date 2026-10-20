# Blender 环境恢复指令：本地容器与 GitHub Actions

**更新日期：2026-10-20**  
**仓库：** https://github.com/752960522qq-ai/blender_1  
**运行版本：** Blender 4.5.14 LTS

> 本文是以后可以直接交给 ChatGPT 执行的恢复指令与排障记录。重要区别：**GitHub Actions 远程流程已经实测通过；ChatGPT 本地容器截至本文件编写时仍不可执行**。不要把前者误报为后者修复成功。

## 一、下次直接复制的恢复口令

> 请查看 `752960522qq-ai/blender_1` 仓库的 `docs/BLENDER_RUNTIME_RECOVERY.md`，按文档**实际操作**恢复 Blender 环境。先检查本地 Shell 和 Python 能否运行；如果最基本的命令都报 ClientError、ServerError 或 ServiceUnavailableError，立即走 GitHub Actions 远程流程，别反复在坏掉的本地容器里解压。若本地命令可运行，再按文档使用经过 SHA256 校验的 Blender 4.5.14 安装包，在临时目录完整解压后替换坏的目录。必须实际试跑 Blender、GLB 导入导出和必要时的 Cycles 渲染，提供本次真实运行日志、产物和失败原因。请区分测试模型与我真正提供的最新版 GLB，不能拿旧 run 或旧模型冒充新测试。

## 二、已经真正通过的远程验证

- 仓库：`752960522qq-ai/blender_1`
- **远程运行编号：39355657356**
- GitHub Actions 记录：https://github.com/752960522qq-ai/blender_1/actions/runs/39355657356
- 结果：`completed / success`，Blender `4.5.14 LTS`
- 实测：远程 Blender 启动、仓库测试 GLB 导入、**模拟 45° 参考图**生成及半透明相机背景、保守对称几何修改、特征锚点位置锁定、Blend 保存、GLB 导出及重新导入、报告生成、artifact 上传。
- 验收日志标志：`SYNTHETIC_45_REFERENCE_READY` 与 `HEAD_V12_45_EDIT_OK`（包含 `"status":"PASS"`）。
- 当次产物（仅保留 7 天）：https://github.com/752960522qq-ai/blender_1/actions/runs/39355657356/artifacts/12235266117

**测试边界：** 该运行使用仓库测试模型和人工生成的背景图，**不是用户真正的 v13 GLB，也不是真实人物参考图；没有完成真人对位或 Cycles 三视图渲染**。先前基础工作流的成功记录：https://github.com/752960522qq-ai/blender_1/actions/runs/39339679265

## 三、方案 A：本地容器坏掉时，走 GitHub Actions

目前相关文件：

- `.github/workflows/blender-remote-worker.yml` + `remote_blender_job.py`：通用 Blender 模型导入导出、参考相机设置、.blend 保存和回读检查；**不修改网格**。
- `.github/workflows/refine-v12-45.yml` + `refine_v12_45.py`：用于保守的 45° 侧脸局部修整；`smoke` 模式使用仓库测试模型，附带合成 45° 背景图。
- `test_blender.py`：通用基础 Blender 测试。

### 3.1 用界面重复验证远程流程

进入 GitHub 仓库 → **Actions → Blender V12 45-Degree Refinement → Run workflow**。

选择 `run_mode=smoke`，其他参数保持默认；等到运行结果 `Success`，打开运行日志，检查 `HEAD_V12_45_EDIT_OK`、`PASS`，再检查 artifacts 是否有实际的 GLB、Blend、report。**这只验证远程平台，不证明最新版人像模型已经被处理。**

通用远程导入导出验证：**Actions → Blender Remote Worker → Run workflow**：

- `run_mode=model_check`
- `model_path=models/head-input.glb`：仅用仓库测试模型
- `reference_view=three_quarter`：45° 参考相机
- `reference_path`：为空时**不会**加载图；填写真实存在的仓库图片路径才加载图。
- 在日志中检查 `REMOTE_BLENDER_MODEL_CHECK_OK` 且 `"result":"PASS"`。

现有远程工作流使用 GitHub 的 Ubuntu 24.04 runner，并安装/缓存经过 SHA256 校验的官方 Blender 4.5.14。**不依赖本地容器可用性。**

如果当前工具不能手动 dispatch，但有 GitHub 仓库写权限，允许在获得用户授权并确有必要时，通过对对应 workflow 或脚本做**实质性修改并提交到 main**来触发 workflow 的 push 规则。不要用历史记录冒充新试跑。

### 3.2 真实建模与隐私注意事项

1. 必须把用户指定的**实际最新版 GLB** 和**实际参考图**提供给远程 runner，才能声称完成了对应的模型精修。
2. `models/head-input.glb` 是旧测试模型，不能冒充 v12/v13。
3. `refine-v12-45.yml` 的 `refine` 模式要求名为 `jill_head_refined_eye_jaw_v12.glb` 的真实输入和真实参考图；`smoke` 不需要真实输入。
4. **仓库为公开仓库。绝对不要未经用户了解并同意就上传人物照片、敏感模型或私有素材到公开仓库或公开 GitHub Release。**需要时改用私有仓库或获用户授权的安全传输方案。
5. 实际修改应保留原有突出锚点位置、保护五官及材质 UV、两侧对称；导出后重新导入并验收。报告应标明确切模型版本、输入文件哈希、实际修改范围。

## 四、先检查本地容器，而不是盲目重装 Blender

首先运行（使用当前会话可调用的执行工具）：

```bash
echo "shell ok"
python3 -c 'print("hello")'
ls -ld /mnt/data
```

**情况 A：以上普通命令直接报 `ClientError`、`ServerError` 或 `ServiceUnavailableError`。**

这是**本地命令执行服务本身**故障，尚未进入 Blender。此时无法从同一个不可用的容器里执行重装命令。应立即启用 GitHub Actions 继续工作，等待容器恢复。**不能**说 GitHub Actions 成功等于本地容器修复。

**情况 B：Shell/Python 正常，但 Blender 程序文件缺失、运行返回 11 或 135。**

历史中曾经出现过 Blender 安装目录仅剩 `readme.html`，以及 `tar` 解压超时造成的半截二进制。处理办法：**校验安装包、在独立暂存目录完整解压、先测试新二进制，成功后才替换旧目录**。

### 4.1 完整重装命令（只在 Shell 能正常工作时执行）

本地原始包预期位置：`/mnt/data/blender-4.5.14-linux-x64.tar.xz`。如果不存在，应要求重新提供官方包，而不是虚构路径。

官方来源：
https://download.blender.org/release/Blender4.5/blender-4.5.14-linux-x64.tar.xz

经现有工作流验证的 SHA256：
`9ba871ff2ecd36526b77432745980b7e6664ecd0c7ca11c48849073dcfe06da3`

```bash
set -euo pipefail
ARCHIVE=/mnt/data/blender-4.5.14-linux-x64.tar.xz
TARGET=/mnt/data/blender-4.5.14-linux-x64
EXPECTED=9ba871ff2ecd36526b77432745980b7e6664ecd0c7ca11c48849073dcfe06da3

test -s "$ARCHIVE"
printf '%s  %s\n' "$EXPECTED" "$ARCHIVE" | sha256sum -c -

STAGE=$(mktemp -d /mnt/data/blender-staging.XXXXXX)
echo "Extracting into $STAGE; must wait until tar finishes"
tar -xJf "$ARCHIVE" -C "$STAGE"

test -x "$STAGE/blender-4.5.14-linux-x64/blender"
"$STAGE/blender-4.5.14-linux-x64/blender" -b --version | head -n 3

if test -e "$TARGET"; then
  mv "$TARGET" "$TARGET.broken.$(date +%s)"
fi
mv "$STAGE/blender-4.5.14-linux-x64" "$TARGET"
rmdir "$STAGE"
"$TARGET/blender" -b --version | head -n 3
echo "BLENDER_BINARY_RESTORED"
```

注意：`tar` 仍在运行、已超时或者执行失败时，不能尝试用半解压目录运行 Blender。SHA256 不一致时应停止，而不是跳过校验。Blender 退出码 11/135 也可能涉及依赖、内存映射、磁盘/文件系统等问题，不保证重装一定修好。

### 4.2 Blender 导入/导出 + Cycles 真实试跑

下面使用当前会话中存在的 v13 模型；若找不到，就退化为立方体测试，并明确写出使用了测试立方体。为降低运行压力，渲染 128×128、CPU 两次采样。

```bash
cat > /mnt/data/blender_recovery_smoke.py <<'PY'
import bpy, os
from mathutils import Vector

source = "/mnt/data/jill_head_refined_eye_jaw_v13.glb"
out = "/mnt/data/blender_recovery_roundtrip.glb"
preview = "/mnt/data/blender_recovery_smoke.png"
bpy.ops.wm.read_factory_settings(use_empty=True)
if os.path.isfile(source):
    bpy.ops.import_scene.gltf(filepath=source)
    print("USER_V13_USED", source)
else:
    bpy.ops.mesh.primitive_cube_add()
    print("TEST_CUBE_USED; v13 is not present")
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
assert meshes
pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector(tuple(min(v[i] for v in pts) for i in range(3)))
hi = Vector(tuple(max(v[i] for v in pts) for i in range(3)))
center = (lo + hi) / 2
span = max((hi-lo)[i] for i in range(3))
dist = max(2.0, span * 2.8)

camdata = bpy.data.cameras.new('SmokeCamera')
camdata.type = 'ORTHO'
camdata.ortho_scale = max((hi.z-lo.z)*1.4, (hi.x-lo.x)*1.5, .5)
cam = bpy.data.objects.new('SmokeCamera', camdata)
bpy.context.collection.objects.link(cam)
cam.location = (center.x, center.y - dist, center.z)
cam.rotation_euler = (center-cam.location).to_track_quat('-Z','Y').to_euler()
bpy.context.scene.camera = cam

light_data = bpy.data.lights.new('SmokeLight','AREA')
light_data.energy = 400
light = bpy.data.objects.new('SmokeLight',light_data)
bpy.context.collection.objects.link(light)
light.location=(center.x-dist*.3,center.y-dist*.4,center.z+dist*.2)
light.rotation_euler=(center-light.location).to_track_quat('-Z','Y').to_euler()

scene=bpy.context.scene
scene.render.engine='CYCLES'
scene.cycles.device='CPU'
scene.cycles.samples=2
scene.render.resolution_x=128
scene.render.resolution_y=128
scene.render.resolution_percentage=100
scene.render.filepath=preview
bpy.ops.render.render(write_still=True)
assert os.path.getsize(preview)>100

bpy.ops.object.select_all(action='DESELECT')
for o in meshes: o.select_set(True)
bpy.context.view_layer.objects.active=meshes[0]
bpy.ops.export_scene.gltf(filepath=out,export_format='GLB',
                         use_selection=True,export_animations=False)
assert os.path.getsize(out)>1000
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=out)
assert any(o.type=='MESH' for o in bpy.context.scene.objects)
print('BLENDER_LOCAL_SMOKE_OK',bpy.app.version_string,out,preview)
PY

/mnt/data/blender-4.5.14-linux-x64/blender -b --factory-startup \
  --python-exit-code 1 --python /mnt/data/blender_recovery_smoke.py
```

成功标准：终端出现 `BLENDER_LOCAL_SMOKE_OK`，且 `blender_recovery_smoke.png`、`blender_recovery_roundtrip.glb` 确实生成。只有这样才能宣称**本地 Blender** 已试跑成功。若显示 `TEST_CUBE_USED`，不能宣称 v13 也已验证。

## 五、每次完成恢复后的验收报告

必须分别说明：

- **运行位置**：本地 ChatGPT 容器、GitHub Actions 还是两者。
- **实际结果**：Shell、Python、Blender 启动、GLB 导入、参考图、Cycles 渲染、GLB 导出与回读、文件产物上传分别通过与否。
- **真实输入**：旧仓库测试模型 + 合成图片，或者用户真实最新版 GLB + 真实参考图，不能混淆。
- **可验证证据**：本次 GitHub run ID、日志 PASS、artifact 链接；或本地明确存在的实际输出文件。
- **尚未完成**：如本地服务故障、真实 GLB 未上传、三视图未渲染，要直说。

不能用旧日志冒充本次试跑；不能凭空提供 GLB 或 PNG 下载链接。

## 六、故障速查表

| 现象 | 处理 |
|---|---|
| Shell 的 `echo ok` 都报 ClientError | 本地命令服务故障；转 GitHub Actions |
| Python `print("hello")` 报 ServerError | 本地 Python 服务故障；转 GitHub Actions |
| Blender 文件缺失/仅剩 readme.html | 暂存目录完整解压，测试后替换 |
| Blender 返回 11、135 | 校验包/依赖/文件系统/完整性，不假设单纯重装必好 |
| tar 解压超时 | 不要运行半成品；重新完整解压 |
| 45° 背景图检测通过但未见真人参考图 | 只是合成图或路径为空；真实对位仍未完成 |
| 远程模型处理成功但不是 v13 | 仅测试环境成功；需重新接入真实 v13 |
| artifact 链接过期 | 重跑或经用户授权保存到长期受控存储 |

---

**简短恢复指令（可复制）：**

“请读取我 GitHub 仓库 `752960522qq-ai/blender_1` 的 `docs/BLENDER_RUNTIME_RECOVERY.md`，严格按照其中的故障分支恢复并实测。先验证本地容器；容器服务不可用就走 GitHub Actions。不要用历史成功冒充当前成功，提供本次日志、运行编号和模型产物，并说明用的是测试素材还是真实最新模型。”
