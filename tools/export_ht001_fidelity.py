from __future__ import annotations

import sys
from pathlib import Path

import bpy

GITHUB_HARD_LIMIT = 100 * 1024 * 1024


def argv_after_double_dash() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def supported_properties() -> set[str]:
    try:
        return set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    except Exception:
        return set()


def scale_images(max_side: int) -> None:
    """Reduce texture resolution only; never touches mesh geometry."""
    for image in bpy.data.images:
        try:
            if image.type in {"RENDER_RESULT", "COMPOSITING"}:
                continue
            width, height = int(image.size[0]), int(image.size[1])
            if width <= 0 or height <= 0:
                continue
            longest = max(width, height)
            if longest <= max_side:
                continue
            factor = max_side / float(longest)
            new_w = max(1, int(round(width * factor)))
            new_h = max(1, int(round(height * factor)))
            print(f"[HT-001] Texture {image.name!r}: {width}x{height} -> {new_w}x{new_h}")
            image.scale(new_w, new_h)
        except Exception as exc:
            print(f"[HT-001] Texture ignorée {getattr(image, 'name', '?')}: {exc}")


def export_exact_geometry(output: Path, texture_max: int) -> None:
    scale_images(texture_max)
    supported = supported_properties()

    kwargs: dict[str, object] = {
        "filepath": str(output),
        "export_format": "GLB",
        "export_texcoords": True,
        "export_normals": True,
        "export_tangents": True,
        "export_materials": "EXPORT",
        "export_cameras": False,
        "export_lights": False,
        "export_animations": False,
        "export_yup": True,
    }

    # CRITICAL: no geometry compression / quantisation.
    if "export_draco_mesh_compression_enable" in supported:
        kwargs["export_draco_mesh_compression_enable"] = False

    if "export_visible" in supported:
        kwargs["export_visible"] = True

    # Do not use export_apply here: let the glTF exporter preserve the evaluated
    # scene using its normal path rather than baking a new destructive copy.

    # Texture quality can be reduced without changing geometry.
    if "export_image_quality" in supported:
        kwargs["export_image_quality"] = 92
    elif "export_jpeg_quality" in supported:
        kwargs["export_jpeg_quality"] = 92

    if supported:
        kwargs = {k: v for k, v in kwargs.items() if k in supported or k == "filepath"}

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    print("[HT-001] Export fidélité: AUCUN Draco, AUCUNE décimation, AUCUNE quantification.")
    result = bpy.ops.export_scene.gltf(**kwargs)
    print(f"[HT-001] Résultat Blender: {result}")

    if not output.exists() or output.stat().st_size < 1024:
        raise RuntimeError("Blender n'a pas créé un GLB valide.")


def mib(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def main() -> None:
    args = argv_after_double_dash()
    if not args:
        raise SystemExit("Chemin de sortie manquant après --")

    output = Path(args[0]).expanduser().resolve()

    # Geometry fidelity takes priority. Only textures are reduced.
    export_exact_geometry(output, texture_max=2048)
    print(f"[HT-001] Taille finale: {mib(output):.2f} MiB")

    if output.stat().st_size <= GITHUB_HARD_LIMIT:
        print("[HT-001] OK pour git push (<100 MiB).")
    else:
        print(
            "[HT-001] ATTENTION: >100 MiB. Ne compresse pas la géométrie. "
            "Réduis uniquement les textures ou utilise un stockage adapté."
        )


if __name__ == "__main__":
    main()
