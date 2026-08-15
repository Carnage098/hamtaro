from __future__ import annotations

import sys
from pathlib import Path

import bpy


def argv_after_double_dash() -> list[str]:
    if '--' not in sys.argv:
        return []
    return sys.argv[sys.argv.index('--') + 1:]


def supported_properties() -> set[str]:
    try:
        return set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    except Exception:
        return set()


def scale_images(max_side: int = 1536) -> None:
    """Redimensionne seulement les textures, jamais le maillage."""
    for image in bpy.data.images:
        try:
            if image.type in {'RENDER_RESULT', 'COMPOSITING'}:
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


def export_raw(output: Path) -> None:
    scale_images(1536)
    supported = supported_properties()

    kwargs: dict[str, object] = {
        'filepath': str(output),
        'export_format': 'GLB',
        'export_texcoords': True,
        'export_normals': True,
        'export_tangents': True,
        'export_materials': 'EXPORT',
        'export_cameras': False,
        'export_lights': False,
        'export_animations': False,
        'export_yup': True,
    }

    # Jamais de compression géométrique destructive côté Blender.
    if 'export_draco_mesh_compression_enable' in supported:
        kwargs['export_draco_mesh_compression_enable'] = False
    if 'export_visible' in supported:
        kwargs['export_visible'] = True
    if 'export_image_quality' in supported:
        kwargs['export_image_quality'] = 92
    elif 'export_jpeg_quality' in supported:
        kwargs['export_jpeg_quality'] = 92

    if supported:
        kwargs = {k: v for k, v in kwargs.items() if k in supported or k == 'filepath'}

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    print('[HT-001] Export RAW fidèle: zéro décimation, zéro Draco.')
    result = bpy.ops.export_scene.gltf(**kwargs)
    print(f'[HT-001] Résultat Blender: {result}')

    if not output.exists() or output.stat().st_size < 1024:
        raise RuntimeError("Blender n'a pas créé un GLB valide.")


def main() -> None:
    args = argv_after_double_dash()
    if not args:
        raise SystemExit('Chemin de sortie manquant après --')
    export_raw(Path(args[0]).expanduser().resolve())


if __name__ == '__main__':
    main()
