from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

TARGET_TRIANGLES = 250_000
MAX_TEXTURE_SIZE = 2048
MIN_MESH_TRIANGLES_TO_DECIMATE = 80_000


def script_args() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def project_root() -> Path:
    args = script_args()
    if args:
        return Path(args[0]).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def tri_count(obj: bpy.types.Object) -> int:
    if obj.type != "MESH" or obj.data is None:
        return 0
    mesh = obj.data
    try:
        mesh.calc_loop_triangles()
        return len(mesh.loop_triangles)
    except Exception:
        return len(mesh.polygons)


def visible_meshes() -> list[bpy.types.Object]:
    return [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and not obj.hide_render
    ]


def optimize_textures() -> None:
    for image in bpy.data.images:
        if image.type != "IMAGE" or not image.has_data:
            continue
        width, height = image.size
        if width <= 0 or height <= 0:
            continue
        longest = max(width, height)
        if longest <= MAX_TEXTURE_SIZE:
            continue
        ratio = MAX_TEXTURE_SIZE / longest
        new_w = max(1, int(round(width * ratio)))
        new_h = max(1, int(round(height * ratio)))
        print(f"[HT-001] Texture {image.name}: {width}x{height} -> {new_w}x{new_h}")
        try:
            image.scale(new_w, new_h)
        except Exception as exc:
            print(f"[HT-001] WARN texture non redimensionnée {image.name}: {exc}")


def optimize_geometry() -> tuple[int, int]:
    meshes = visible_meshes()
    before = sum(tri_count(obj) for obj in meshes)
    if before <= TARGET_TRIANGLES or before <= 0:
        print(f"[HT-001] Triangles: {before:,} (pas de décimation nécessaire)")
        return before, before

    candidates = [obj for obj in meshes if tri_count(obj) >= MIN_MESH_TRIANGLES_TO_DECIMATE]
    candidate_tris = sum(tri_count(obj) for obj in candidates)
    protected_tris = before - candidate_tris
    budget_for_candidates = max(1, TARGET_TRIANGLES - protected_tris)
    ratio = min(1.0, max(0.03, budget_for_candidates / max(1, candidate_tris)))

    print(f"[HT-001] Triangles avant: {before:,}")
    print(f"[HT-001] Ratio de décimation des gros meshes: {ratio:.4f}")

    for obj in candidates:
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        try:
            modifier = obj.modifiers.new(name="HT001_WEB_DECIMATE", type="DECIMATE")
            modifier.decimate_type = "COLLAPSE"
            modifier.ratio = ratio
            modifier.use_collapse_triangulate = True
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        except Exception as exc:
            print(f"[HT-001] WARN décimation ignorée pour {obj.name}: {exc}")

    after = sum(tri_count(obj) for obj in visible_meshes())
    print(f"[HT-001] Triangles après: {after:,}")
    return before, after


def export_glb(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    desired = {
        "filepath": str(output),
        "export_format": "GLB",
        "use_visible": True,
        "export_cameras": False,
        "export_lights": False,
        "export_animations": False,
        "export_apply": True,
        "export_texcoords": True,
        "export_normals": True,
        "export_materials": "EXPORT",
        "export_yup": True,
        "export_image_format": "AUTO",
        "export_image_quality": 85,
    }
    try:
        supported = {
            prop.identifier
            for prop in bpy.ops.export_scene.gltf.get_rna_type().properties
        }
        kwargs = {key: value for key, value in desired.items() if key in supported}
    except Exception:
        kwargs = desired

    print(f"[HT-001] Export GLB -> {output}")
    result = bpy.ops.export_scene.gltf(**kwargs)
    if "FINISHED" not in result:
        raise RuntimeError(f"Export glTF échoué: {result}")


def update_catalog(root: Path, output: Path) -> None:
    catalog = root / "web" / "data" / "trophies.json"
    if not catalog.exists():
        return
    data = json.loads(catalog.read_text(encoding="utf-8"))
    size_mb = round(output.stat().st_size / 1024 / 1024, 1)
    for trophy in data.get("trophies", []):
        if str(trophy.get("id", "")).upper() == "HT-001":
            trophy["model_path"] = "/static/models/trophies/ht-001.glb"
            trophy["model_size_mb"] = size_mb
            trophy["source_master"] = "master/HT-001_Trophy_Kuriboh_Champion_Final_v3.blend"
            trophy["web_build"] = "optimized-glb"
    catalog.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[HT-001] Catalogue mis à jour ({size_mb} Mo).")


def main() -> None:
    root = project_root()
    output = root / "web" / "static" / "models" / "trophies" / "ht-001.glb"

    print("[HT-001] Master chargé:", bpy.data.filepath)
    print("[HT-001] Le .blend original ne sera PAS sauvegardé/modifié.")

    optimize_textures()
    before, after = optimize_geometry()
    export_glb(output)
    update_catalog(root, output)

    print("\n✅ HT-001 WEB BUILD TERMINÉ")
    print(f"GLB : {output}")
    print(f"Taille : {output.stat().st_size / 1024 / 1024:.1f} Mo")
    print(f"Triangles : {before:,} -> {after:,}")


if __name__ == "__main__":
    main()
