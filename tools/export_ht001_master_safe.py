from __future__ import annotations

import os
import sys
from pathlib import Path

import bpy

LIMIT_BYTES = 25 * 1024 * 1024


def _argv_after_double_dash() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def _operator_properties() -> set[str]:
    try:
        return set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    except Exception:
        return set()


def _scale_images(max_side: int) -> None:
    """Downscale textures in memory only. The .blend master is never saved."""
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
            print(
                f"[HT-001] Texture {image.name!r}: "
                f"{width}x{height} -> {new_w}x{new_h}"
            )
            image.scale(new_w, new_h)
        except Exception as exc:
            print(f"[HT-001] Texture ignorée {getattr(image, 'name', '?')}: {exc}")


def _export(output: Path, *, texture_max: int, tangents: bool, strong: bool) -> None:
    _scale_images(texture_max)

    supported = _operator_properties()
    kwargs: dict[str, object] = {
        "filepath": str(output),
        "export_format": "GLB",
        "export_texcoords": True,
        "export_normals": True,
        "export_tangents": tangents,
        "export_materials": "EXPORT",
        "export_cameras": False,
        "export_lights": False,
        "export_animations": False,
        "export_yup": True,
    }

    # Keep only objects that are actually visible in the final master when
    # the installed Blender exposes this option.
    if "export_visible" in supported:
        kwargs["export_visible"] = True

    if "export_apply" in supported:
        kwargs["export_apply"] = True

    # Lossless-topology geometry compression: no Decimate modifier, no mesh
    # simplification. Quantization can reduce precision slightly but does not
    # fracture/rebuild the topology like the previous lightweight model.
    if "export_draco_mesh_compression_enable" in supported:
        kwargs["export_draco_mesh_compression_enable"] = True
        kwargs["export_draco_mesh_compression_level"] = 10 if strong else 6
        kwargs["export_draco_position_quantization"] = 13 if strong else 14
        kwargs["export_draco_normal_quantization"] = 9 if strong else 10
        kwargs["export_draco_texcoord_quantization"] = 11 if strong else 12
        if "export_draco_color_quantization" in supported:
            kwargs["export_draco_color_quantization"] = 10
        if "export_draco_generic_quantization" in supported:
            kwargs["export_draco_generic_quantization"] = 12
    else:
        print("[HT-001] Draco n'est pas exposé par cette version de Blender.")

    # JPEG quality option changed names between exporter versions.
    if "export_image_quality" in supported:
        kwargs["export_image_quality"] = 88 if strong else 92
    elif "export_jpeg_quality" in supported:
        kwargs["export_jpeg_quality"] = 88 if strong else 92

    # Filter to the properties supported by the user's Blender build.
    if supported:
        kwargs = {k: v for k, v in kwargs.items() if k in supported or k == "filepath"}

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    print("[HT-001] Export du master V3...")
    result = bpy.ops.export_scene.gltf(**kwargs)
    print(f"[HT-001] Résultat Blender: {result}")

    if not output.exists() or output.stat().st_size < 1024:
        raise RuntimeError("Blender n'a pas créé un GLB valide.")


def _size_mib(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def main() -> None:
    args = _argv_after_double_dash()
    if not args:
        raise SystemExit("Chemin de sortie manquant après --")

    output = Path(args[0]).expanduser().resolve()

    # PASS 1: highest fidelity web version. No topology simplification.
    _export(output, texture_max=2048, tangents=True, strong=False)
    first_size = output.stat().st_size
    print(f"[HT-001] Passe haute fidélité: {_size_mib(output):.2f} MiB")

    if first_size <= LIMIT_BYTES:
        print("[HT-001] OK: modèle sous 25 MiB sans décimation.")
        return

    # PASS 2: still no decimation. Stronger Draco, 1K textures, tangents
    # omitted. This preserves the actual geometry and silhouette.
    print("[HT-001] > 25 MiB: deuxième passe non destructive.")
    _export(output, texture_max=1024, tangents=False, strong=True)
    second_size = output.stat().st_size
    print(f"[HT-001] Passe compacte: {_size_mib(output):.2f} MiB")

    if second_size <= LIMIT_BYTES:
        print("[HT-001] OK: modèle sous 25 MiB sans décimation.")
    else:
        print(
            "[HT-001] Le modèle reste au-dessus de 25 MiB. "
            "Il est néanmoins fidèle au master. Ne le décime pas: "
            "utilise git push depuis le Terminal (GitHub accepte les fichiers "
            "jusqu'à 100 MiB) ou Git LFS si nécessaire."
        )


if __name__ == "__main__":
    main()
