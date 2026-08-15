from __future__ import annotations

import sys
from pathlib import Path

import bpy


def argv_after_double_dash() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def supported_properties() -> set[str]:
    try:
        return set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    except Exception:
        return set()


def scale_images(max_side: int = 1024) -> None:
    """Allège uniquement les textures. Le fichier .blend d'origine n'est jamais sauvegardé."""
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


def export_light_premium(output: Path) -> None:
    supported = supported_properties()

    if "export_draco_mesh_compression_enable" not in supported:
        raise RuntimeError(
            "Cette version de Blender ne propose pas la compression Draco dans l'export glTF. "
            "Mets Blender à jour avant de générer le modèle Web Light."
        )

    scale_images(1024)

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
        # Aucun simplify / aucune décimation : tous les polygones sont conservés.
        "export_draco_mesh_compression_enable": True,
        "export_draco_mesh_compression_level": 7,
        # Quantification volontairement haute pour conserver la forme.
        "export_draco_position_quantization": 16,
        "export_draco_normal_quantization": 12,
        "export_draco_texcoord_quantization": 14,
        "export_draco_color_quantization": 10,
        "export_draco_generic_quantization": 12,
    }

    if "export_visible" in supported:
        kwargs["export_visible"] = True
    if "export_image_quality" in supported:
        kwargs["export_image_quality"] = 82
    elif "export_jpeg_quality" in supported:
        kwargs["export_jpeg_quality"] = 82

    kwargs = {key: value for key, value in kwargs.items() if key == "filepath" or key in supported}

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    print("[HT-001] Export WEB LIGHT PREMIUM")
    print("[HT-001] Aucun polygone supprimé.")
    print("[HT-001] Draco haute précision: position=16, normales=12, UV=14.")

    result = bpy.ops.export_scene.gltf(**kwargs)
    print(f"[HT-001] Résultat Blender: {result}")

    if not output.exists() or output.stat().st_size < 1024:
        raise RuntimeError("Blender n'a pas créé un GLB valide.")


def main() -> None:
    args = argv_after_double_dash()
    if not args:
        raise SystemExit("Chemin de sortie manquant après --")

    output = Path(args[0]).expanduser().resolve()
    export_light_premium(output)
    size_mib = output.stat().st_size / (1024 * 1024)
    print(f"[HT-001] Taille finale: {size_mib:.2f} MiB")

    if size_mib <= 25:
        print("[HT-001] ✅ Taille adaptée au site et à l'upload GitHub navigateur (<25 MiB).")
    else:
        print("[HT-001] ⚠️ Le modèle reste >25 MiB, mais aucun détail géométrique n'a été supprimé.")


if __name__ == "__main__":
    main()
