#!/usr/bin/env python3
"""Restore v12 eyes/brows/lashes and textures while preserving v13 face geometry.

This is NOT a Blender export. It patches the GLB binary container directly:
- v12 is the BASE, preserving all meshes, skin, materials, textures and iris details.
- v13's FACE POSITION accessor replaces the matching one in v12 (same vertex layout required).
- v13's NECK mesh primitive geometry replaces v12 neck geometry, retaining v12 material.
It refuses mismatched face topology or unexpected coordinate changes.

Usage:
  python3 tools/repair_glb_features.py V12.glb V13.glb OUTPUT.glb
"""
import argparse
import copy
import json
import os
import struct
from pathlib import Path

import numpy as np

MAGIC = b"glTF"
COMPONENTS = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2",
              5125: "<u4", 5126: "<f4"}
ELEMENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
            "MAT2": 4, "MAT3": 9, "MAT4": 16}


def parse_glb(path):
    data = Path(path).read_bytes()
    if len(data) < 20 or data[:4] != MAGIC:
        raise ValueError(f"Not a valid GLB: {path}")
    magic, version, total = struct.unpack_from("<4sII", data)
    if version != 2 or total != len(data):
        raise ValueError(f"GLB header invalid: {path}")
    pos = 12
    chunks = {}
    while pos < total:
        size, ctype = struct.unpack_from("<I4s", data, pos)
        pos += 8
        if pos + size > len(data):
            raise ValueError("Truncated GLB chunk")
        chunks[ctype] = data[pos:pos + size]
        pos += size
    if b"JSON" not in chunks or b"BIN\x00" not in chunks:
        raise ValueError("GLB missing JSON or BIN chunk")
    info = json.loads(chunks[b"JSON"])
    if len(info.get("buffers", [])) != 1:
        raise ValueError("Only standard single-buffer GLBs are supported")
    return info, chunks[b"BIN\x00"]


def accessor_values(doc, buffer, accessor_idx):
    acc = doc["accessors"][accessor_idx]
    if "sparse" in acc:
        raise ValueError("Sparse accessors are unsupported")
    if "bufferView" not in acc:
        raise ValueError("Accessor without bufferView is unsupported")
    view = doc["bufferViews"][acc["bufferView"]]
    if view.get("buffer", 0) != 0 or "extensions" in view:
        raise ValueError("Unsupported buffer view")
    dtype = np.dtype(COMPONENTS[acc["componentType"]])
    n = ELEMENTS[acc["type"]]
    stride = view.get("byteStride", dtype.itemsize * n)
    offset = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    array = np.ndarray((acc["count"], n), dtype=dtype, buffer=buffer,
                       offset=offset, strides=(stride, dtype.itemsize))
    return array.copy()


def mesh_for_node(doc, needle):
    found = []
    for node in doc["nodes"]:
        name = node.get("name", "").lower()
        if needle == "face":
            match = "face" in name and "eye" not in name and "neck" not in name
        else:
            match = "neck" in name
        if match and "mesh" in node:
            mesh = doc["meshes"][node["mesh"]]
            for prim in mesh["primitives"]:
                ai = prim.get("attributes", {}).get("POSITION")
                if ai is not None:
                    found.append((node["mesh"], prim,
                                  doc["accessors"][ai]["count"], node.get("name", "")))
    if not found:
        raise ValueError(f"No {needle} mesh found")
    return max(found, key=lambda x: x[2])


class AppendAccessors:
    def __init__(self, destination_doc, destination_buffer, source_doc, source_buffer):
        self.dest = destination_doc
        self.data = bytearray(destination_buffer)
        self.source = source_doc
        self.source_data = source_buffer
        self.views = {}
        self.accessors = {}

    def view(self, src_idx):
        if src_idx in self.views:
            return self.views[src_idx]
        view = copy.deepcopy(self.source["bufferViews"][src_idx])
        if view.get("buffer", 0) != 0 or "extensions" in view:
            raise ValueError("Unsupported source buffer view")
        start = view.get("byteOffset", 0)
        end = start + view["byteLength"]
        while len(self.data) % 4:
            self.data.append(0)
        view["byteOffset"] = len(self.data)
        view["buffer"] = 0
        self.data.extend(self.source_data[start:end])
        idx = len(self.dest["bufferViews"])
        self.dest["bufferViews"].append(view)
        self.views[src_idx] = idx
        return idx

    def accessor(self, src_idx):
        if src_idx in self.accessors:
            return self.accessors[src_idx]
        acc = copy.deepcopy(self.source["accessors"][src_idx])
        if "sparse" in acc or "bufferView" not in acc:
            raise ValueError("Unsupported source accessor")
        acc["bufferView"] = self.view(acc["bufferView"])
        idx = len(self.dest["accessors"])
        self.dest["accessors"].append(acc)
        self.accessors[src_idx] = idx
        return idx


def emit_glb(path, doc, binary):
    binary = bytes(binary)
    doc["buffers"][0]["byteLength"] = len(binary)
    j = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf8")
    j += b" " * ((-len(j)) % 4)
    binary += b"\x00" * ((-len(binary)) % 4)
    total = 12 + 8 + len(j) + 8 + len(binary)
    blob = (struct.pack("<4sII", MAGIC, 2, total) +
            struct.pack("<I4s", len(j), b"JSON") + j +
            struct.pack("<I4s", len(binary), b"BIN\x00") + binary)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(blob)


def repair(v12, v13, output):
    if Path(v12).resolve() == Path(output).resolve() or Path(v13).resolve() == Path(output).resolve():
        raise ValueError("Output must not overwrite the original")
    baseline, bbase = parse_glb(v12)
    newer, bnew = parse_glb(v13)
    base_idx, base_face, _, base_name = mesh_for_node(baseline, "face")
    new_idx, new_face, _, new_name = mesh_for_node(newer, "face")
    print("FACE_TARGET", base_name, "SOURCE", new_name, flush=True)
    if len(baseline["meshes"][base_idx]["primitives"]) != 1 or len(newer["meshes"][new_idx]["primitives"]) != 1:
        raise ValueError("This repair requires single-primitive face meshes")
    if base_face.get("mode", 4) != 4 or new_face.get("mode", 4) != 4:
        raise ValueError("Requires triangle mesh faces")
    bi, ni = base_face["indices"], new_face["indices"]
    base_indexes = accessor_values(baseline, bbase, bi).reshape(-1)
    new_indexes = accessor_values(newer, bnew, ni).reshape(-1)
    if not np.array_equal(base_indexes, new_indexes):
        raise ValueError("Face triangle-index mapping changed between v12 and v13; refusing unsafe texture/UV transplantation")
    bp = accessor_values(baseline, bbase, base_face["attributes"]["POSITION"])
    np13 = accessor_values(newer, bnew, new_face["attributes"]["POSITION"])
    if bp.shape != np13.shape or bp.shape[1] != 3:
        raise ValueError("Face vertex layout changed; cannot safely preserve v13 shape")
    displacement = np.linalg.norm((np13-bp).astype(np.float64), axis=1)
    if np.quantile(displacement, 0.999) > 0.025 or not np.isfinite(np13).all():
        raise ValueError("Unexpected large face-coordinate change; refusing unsafe transplant")

    # Copy raw v13 POSITION into v12 while retaining ALL v12 texture/material data.
    copier = AppendAccessors(baseline, bbase, newer, bnew)
    base_face["attributes"]["POSITION"] = copier.accessor(new_face["attributes"]["POSITION"])
    neck_fixed = False
    try:
        _, old_neck, _, old_neck_name = mesh_for_node(baseline, "neck")
        _, new_neck, _, new_neck_name = mesh_for_node(newer, "neck")
        if old_neck.get("mode", 4) != 4 or new_neck.get("mode", 4) != 4:
            raise ValueError("Unsupported neck mesh mode")
        # Keep v12's material/texture index but use the trimmed v13 neck geometry.
        old_neck["attributes"] = {
            key: copier.accessor(value) for key, value in new_neck["attributes"].items()
        }
        if "indices" in new_neck:
            old_neck["indices"] = copier.accessor(new_neck["indices"])
        else:
            old_neck.pop("indices", None)
        neck_fixed = True
    except ValueError as e:
        # Some models have neck built into the face rather than its own object.
        print("NECK_NOT_REPLACED", str(e), flush=True)
    emit_glb(output, baseline, copier.data)

    verified, verified_bin = parse_glb(output)
    _, verify_face, _, _ = mesh_for_node(verified, "face")
    finalpos = accessor_values(verified, verified_bin, verify_face["attributes"]["POSITION"])
    if not np.array_equal(finalpos, np13):
        raise RuntimeError("Face geometry was not preserved")
    # Ensure all original GLB meshes/materials/images remain in the output.
    if len(verified["meshes"]) != len(parse_glb(v12)[0]["meshes"]):
        raise RuntimeError("Mesh count changed")
    print("GLB_FEATURE_RESTORE_OK", json.dumps({
        "output": output,
        "face_vertices": len(np13),
        "max_face_position_difference_mm": round(float(displacement.max()*1000),4),
        "v13_neck_geometry_transferred": neck_fixed,
        "v12_material_count": len(verified.get("materials", [])),
        "v12_images_retained": len(verified.get("images", [])),
        "output_bytes": os.path.getsize(output)
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("v12", help="v12 GLB with correct brows, lashes, and eyes")
    parser.add_argument("v13", help="v13 GLB with face/neck geometry modifications")
    parser.add_argument("output", help="repaired output GLB")
    args = parser.parse_args()
    repair(args.v12, args.v13, args.output)
