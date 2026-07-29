import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from urllib.parse import quote

_cache: Optional[Dict[str, Any]] = None

# Default manifest path (project root)
MANIFEST_PATH = Path(__file__).parent.parent.parent / "manifest.json"

# Images directory configuration
IMAGES_DIRECTORY = os.getenv("IMAGES_DIRECTORY", "images")

def get_images_directory() -> Path:
    """Resolve the images directory path from environment variable"""
    project_root = Path(__file__).parent.parent.parent
    images_dir_str = IMAGES_DIRECTORY
    if os.path.isabs(images_dir_str):
        return Path(images_dir_str)
    else:
        return project_root / images_dir_str

# Supported image extensions (duplicate to avoid circular import)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tiff", ".tif"}

# Aspect ratio logic (duplicate to avoid circular import)
ASPECT_RATIO_MAP = [
    (1.15, "1:1"),
    (1.4, "4:3"),
    (1.6, "3:2"),
    (1.9, "16:9"),
    (float('inf'), "2:3"),
]
ASPECT_RATIO_SKIP_EXTENSIONS = {".svg", ".ico"}

def get_aspect_ratio(width: int, height: int) -> str:
    if width == 0 or height == 0:
        return "unknown"
    is_landscape = width >= height
    if is_landscape:
        ratio = width / height
    else:
        ratio = height / width
    for threshold, ratio_str in ASPECT_RATIO_MAP:
        if ratio <= threshold:
            if not is_landscape and ratio_str != "1:1":
                parts = ratio_str.split(':')
                return f"{parts[1]}:{parts[0]}"
            return ratio_str
    return "unknown"

def process_image_file(image_path: Path, images_dir: Path) -> Dict[str, Any] | None:
    try:
        stat = image_path.stat()
        relative_path = image_path.relative_to(images_dir)
        url_path_parts = ["/api/images"] + [quote(part) for part in relative_path.parts]
        url = "/".join(url_path_parts)
        width, height, aspect_ratio = 0, 0, "unknown"
        if image_path.suffix.lower() not in ASPECT_RATIO_SKIP_EXTENSIONS:
            try:
                with Image.open(image_path) as img:
                    width, height = img.size
                    aspect_ratio = get_aspect_ratio(width, height)
            except Exception:
                pass
        return {
            "path": str(relative_path),
            "full_path": str(image_path),
            "relative_path": str(relative_path),
            "filename": image_path.name,
            "extension": image_path.suffix.lower(),
            "_mtime": stat.st_mtime,
            "size": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "url": url,
            "width": width,
            "height": height,
            "aspect_ratio": aspect_ratio,
        }
    except (OSError, PermissionError):
        return None


def get_cached_images() -> Optional[Dict[str, Any]]:
    return _cache


def save_manifest(data: Dict[str, Any]):
    global _cache
    try:
        with open(MANIFEST_PATH, 'w') as f:
            json.dump(data, f, indent=2)
        _cache = data
    except Exception as e:
        print(f"Error saving manifest: {e}")


def load_manifest() -> Optional[Dict[str, Any]]:
    global _cache
    if not MANIFEST_PATH.exists():
        return None
    try:
        with open(MANIFEST_PATH, 'r') as f:
            manifest_data = json.load(f)
        _cache = manifest_data
        return manifest_data
    except Exception as e:
        print(f"Error loading manifest: {e}")
        return None


def _scan_directory(images_dir: Path) -> Dict[str, float]:
    """Fast stat-scan of the image directory tree.
    Returns {relative_path: mtime}. No PIL, no file reads — just stat() calls.
    """
    result = {}
    for dirpath, dirnames, filenames in os.walk(str(images_dir)):
        # Skip hidden directories
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in IMAGE_EXTENSIONS:
                continue
            full_path = os.path.join(dirpath, filename)
            try:
                stat_result = os.stat(full_path)
                rel_path = os.path.relpath(full_path, str(images_dir))
                result[rel_path] = stat_result.st_mtime
            except OSError:
                continue
    return result


def sync_manifest(images_dir: Path) -> Dict[str, Any]:
    """
    Incrementally sync the manifest with the filesystem.

    1. Stat-scan the directory tree (no PIL) — fast
    2. Compare mtimes against the existing manifest
    3. Only PIL-open files that are new or changed
    4. Drop records for files no longer on disk
    5. Recalculate aspect ratio counts, sort, save

    Also used for the initial cold-start (no existing manifest to compare).
    """
    global _cache
    _cache = None

    if not images_dir.exists():
        raise ValueError(f"Images directory does not exist: {images_dir}")

    # 1. Stat-scan disk (fast, no PIL) → {relative_path: mtime}
    current_files = _scan_directory(images_dir)

    # 2. Load existing manifest for mtime comparison
    old_manifest = load_manifest()
    old_images = {}
    if old_manifest and "images" in old_manifest:
        old_images = {img["path"]: img for img in old_manifest["images"]}

    # 3. Separate unchanged vs changed/new files
    images = []
    pil_paths = []

    for rel_path, mtime in current_files.items():
        old_record = old_images.get(rel_path)
        if old_record and old_record.get("_mtime") == mtime:
            # Unchanged — reuse cached record entirely (no PIL)
            images.append(old_record)
        else:
            # New or changed — needs PIL
            pil_paths.append(images_dir / rel_path)

    # Process PIL work in parallel
    if pil_paths:
        workers = min(32, (os.cpu_count() or 1) * 2)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = executor.map(process_image_file, pil_paths, [images_dir] * len(pil_paths))
            for result in results:
                if result is not None:
                    images.append(result)

    # 4. Sort for consistent ordering
    images.sort(key=lambda x: x["path"])

    # 5. Recalculate aspect ratio counts
    aspect_ratio_counts = {}
    for img in images:
        ar = img.get("aspect_ratio", "unknown")
        if ar != "unknown":
            aspect_ratio_counts[ar] = aspect_ratio_counts.get(ar, 0) + 1

    result = {
        "directory": str(images_dir),
        "total_images": len(images),
        "images": images,
        "aspect_ratios": aspect_ratio_counts,
    }

    _cache = result
    save_manifest(result)

    changed = len(pil_paths)
    if changed:
        print(f"sync_manifest: {changed} files processed (new/changed), {len(images)} total")
    else:
        print(f"sync_manifest: no changes, {len(images)} total images")

    return result


def regenerate_manifest(images_dir: Path) -> Dict[str, Any]:
    """
    Full re-scan: PIL-open every image file from scratch.
    Nuclear option for when sync state may be corrupted or a clean manifest is desired.
    """
    global _cache
    _cache = None

    if not images_dir.exists():
        raise ValueError(f"Images directory does not exist: {images_dir}")

    # Find all image files
    image_paths = [
        p for p in images_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]

    # Process ALL images with PIL in parallel
    images = []
    workers = min(32, (os.cpu_count() or 1) * 2)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = executor.map(process_image_file, image_paths, [images_dir] * len(image_paths))
        for result in results:
            if result is not None:
                images.append(result)

    images.sort(key=lambda x: x["path"])

    aspect_ratio_counts = {}
    for img in images:
        ar = img.get("aspect_ratio", "unknown")
        if ar != "unknown":
            aspect_ratio_counts[ar] = aspect_ratio_counts.get(ar, 0) + 1

    result = {
        "directory": str(images_dir),
        "total_images": len(images),
        "images": images,
        "aspect_ratios": aspect_ratio_counts,
    }

    _cache = result
    save_manifest(result)

    print(f"regenerate_manifest: {len(images)} total images (full re-scan)")
    return result


# Fields to expose to the client (strip internal/sync fields)
CLIENT_IMAGE_FIELDS = {"path", "filename", "url", "width", "height", "aspect_ratio"}


def image_to_client(img: Dict[str, Any]) -> Dict[str, Any]:
    """Strip internal/sync-only fields from an image record for client consumption."""
    return {k: v for k, v in img.items() if k in CLIENT_IMAGE_FIELDS}


def build_summary(images_dir: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a lightweight summary from the cached manifest (no image details).

    Returns:
        dict with "directory", "total_images", "folders", "aspect_ratios"
        where "folders" is a list of {name, count, thumbnail_url}
        and "aspect_ratios" is {ratio_label: count}.
    """
    images = manifest.get("images", [])

    folder_map: Dict[str, dict] = {}
    aspect_ratios: Dict[str, int] = {}

    for img in images:
        path_str = img.get("path", "")
        parts = path_str.split("/")
        if len(parts) > 1:
            folder = parts[-2]
            if folder not in folder_map:
                folder_map[folder] = {"count": 0, "thumbnail_url": img.get("url", "")}
            folder_map[folder]["count"] += 1

        ar = img.get("aspect_ratio", "unknown")
        if ar != "unknown":
            aspect_ratios[ar] = aspect_ratios.get(ar, 0) + 1

    folders = [
        {"name": name, **info}
        for name, info in sorted(folder_map.items())
    ]

    return {
        "directory": str(images_dir),
        "total_images": len(images),
        "folders": folders,
        "aspect_ratios": aspect_ratios,
    }


# Backward-compatible alias
init_manifest = sync_manifest