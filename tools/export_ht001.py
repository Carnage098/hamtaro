from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

# Objectif volontairement plus bas que la limite GitHub afin de garder une marge.
MAX_FILE_BYTES = 22 * 1024 * 1024
HARD_LIMIT_BYTES = 25 * 1024 * 1024
INITIAL_TARGET_TRIANGLES = 220_000
MIN_TARGET_TRIANGLES = 90_000
MIN_MESH_TRIANGLES_TO_DECIMATE = 50_000
TEXTURE_STEPS = (2048, 1536, 1024)
MAX_PASSES = 5


def script_args() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def project_root() -> Path:
    args = script_args()
    return Path(args[0]).expanduser().resolve() if args else Path.cwd()


def tri_count(obj: bpy.types.Object) -> int:
    if obj.type != "MESH" or obj.data is None:
        return 0
    try:
        obj.data.calc_loop_triangles()
        return len(obj.data.loop_triangles)
    except Exception:
        return len(obj.data.polygons)


def visible_meshes() -> list[bpy.types.Object]:
    return [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and not obj.hide_render
    ]


def convert_geometry_to_meshes() -> None:
    """Convertit texte/courbes visibles en mesh dans la copie mémoire uniquement."""
    candidates = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type in {"CURVE", "FONT", "SURFACE", "META"} and not obj.hide_render
    ]
    for obj in candidates:
        try:
            bpy.ops.object.select_all(action="DESELECT")
            obj.hide_viewport = False
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.convert(target="MESH")
            print(f"[HT-001] Converti en mesh : {obj.name}")
        except Exception as exc:
            print(f"[HT-001] WARN conversion ignorée pour {obj.name}: {exc}")


def resize_textures(max_size: int) -> None:
    for image in bpy.data.images:
        if image.type != "IMAGE" or not image.has_data:
            continue
        width, height = image.size
        if width <= 0 or height <= 0:
            continue
        longest = max(width, height)
        if longest <= max_size:
            continue
        ratio = max_size / longest
        new_w = max(1, int(round(width * ratio)))
        new_h = max(1, int(round(height * ratio)))
        try:
            print(f"[HT-001] Texture {image.name}: {width}x{height} -> {new_w}x{new_h}")
            image.scale(new_w, new_h)
        except Exception as exc:
            print(f"[HT-001] WARN texture non redimensionnée {image.name}: {exc}")


def decimate_to_target(target_triangles: int) -> tuple[int, int]:
    meshes = visible_meshes()
    before = sum(tri_count(obj) for obj in meshes)
    if before <= target_triangles or before <= 0:
        return before, before

    # Les petits objets (texte, plaque, détails) sont protégés autant que possible.
    candidates = [obj for obj in meshes if tri_count(obj) >= MIN_MESH_TRIANGLES_TO_DECIMATE]
    candidate_tris = sum(tri_count(obj) for obj in candidates)
    protected_tris = before - candidate_tris
    if candidate_tris <= 0:
        return before, before

    budget = max(1, target_triangles - protected_tris)
    ratio = min(1.0, max(0.025, budget / candidate_tris))
    print(
        f"[HT-001] Décimation: {before:,} triangles -> cible {target_triangles:,} "
        f"(ratio gros meshes {ratio:.4f})"
    )

    for obj in candidates:
        bpy.ops.object.select_all(action="DESELECT")
        obj.hide_viewport = False
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        try:
            modifier = obj.modifiers.new(name="HT001_WEB_DECIMATE", type="DECIMATE")
            modifier.decimate_type = "COLLAPSE"
            modifier.ratio = ratio
            modifier.use_collapse_triangulate = True
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        except Exception as exc:
            print(f"[HT-001] WARN décimation ignorée pour {obj.name}: {exc}")

    after = sum(tri_count(obj) for obj in visible_meshes())
    print(f"[HT-001] Triangles après passe: {after:,}")
    return before, after


def gltf_supported_properties() -> set[str]:
    try:
        return {
            prop.identifier
            for prop in bpy.ops.export_scene.gltf.get_rna_type().properties
        }
    except Exception:
        return set()


def export_glb(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    supported = gltf_supported_properties()

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
        "export_image_format": "JPEG",
        "export_image_quality": 82,
        # Active Draco uniquement si cette version de Blender le propose.
        "export_draco_mesh_compression_enable": True,
        "export_draco_mesh_compression_level": 6,
        "export_draco_position_quantization": 14,
        "export_draco_normal_quantization": 10,
        "export_draco_texcoord_quantization": 12,
    }

    kwargs = {k: v for k, v in desired.items() if not supported or k in supported}
    print(f"[HT-001] Export -> {output}")
    try:
        result = bpy.ops.export_scene.gltf(**kwargs)
    except Exception as exc:
        # Certaines installations n'ont pas Draco : second essai sans options Draco.
        print(f"[HT-001] Export compressé indisponible ({exc}); nouvel essai standard.")
        kwargs = {k: v for k, v in kwargs.items() if "draco" not in k}
        result = bpy.ops.export_scene.gltf(**kwargs)

    if "FINISHED" not in result:
        raise RuntimeError(f"Export glTF échoué: {result}")


def file_mb(path: Path) -> float:
    return path.stat().st_size / 1024 / 1024


def update_catalog(root: Path, output: Path, triangles: int) -> None:
    catalog = root / "web" / "data" / "trophies.json"
    if not catalog.exists():
        return
    data = json.loads(catalog.read_text(encoding="utf-8"))
    for trophy in data.get("trophies", []):
        if str(trophy.get("id", "")).upper() == "HT-001":
            trophy["model_path"] = "/static/models/trophies/ht-001.glb"
            trophy["model_size_mb"] = round(file_mb(output), 2)
            trophy["web_triangles"] = triangles
            trophy["source_master"] = "Trophy_Kuriboh_Champion_Final_v3.blend"
            trophy["web_build"] = "github-optimized-glb"
    catalog.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    root = project_root()
    output = root / "web" / "static" / "models" / "trophies" / "ht-001.glb"

    print("[HT-001] Master exact chargé :", bpy.data.filepath)
    print("[HT-001] Le fichier .blend original ne sera PAS sauvegardé ni modifié.")

    convert_geometry_to_meshes()

    target = INITIAL_TARGET_TRIANGLES
    last_triangles = sum(tri_count(obj) for obj in visible_meshes())

    for pass_index in range(MAX_PASSES):
        texture_limit = TEXTURE_STEPS[min(pass_index, len(TEXTURE_STEPS) - 1)]
        resize_textures(texture_limit)
        _, last_triangles = decimate_to_target(target)
        export_glb(output)

        size = output.stat().st_size
        print(
            f"[HT-001] Passe {pass_index + 1}: {file_mb(output):.2f} Mo, "
            f"{last_triangles:,} triangles, textures <= {texture_limit}px"
        )
        if size <= MAX_FILE_BYTES:
            break

        target = max(MIN_TARGET_TRIANGLES, int(target * 0.72))
    else:
        print("[HT-001] Toutes les passes d'optimisation ont été utilisées.")

    size = output.stat().st_size
    update_catalog(root, output, last_triangles)

    print("\n========================================")
    print("✅ HT-001 WEB BUILD TERMINÉ")
    print(f"GLB       : {output}")
    print(f"Taille    : {file_mb(output):.2f} Mo")
    print(f"Triangles : {last_triangles:,}")
    print("========================================")

    if size >= HARD_LIMIT_BYTES:
        raise RuntimeError(
            "Le GLB dépasse encore 25 Mo. Ne l'envoie pas sur GitHub. "
            "Une optimisation supplémentaire est nécessaire."
        )


if __name__ == "__main__":
    main()
