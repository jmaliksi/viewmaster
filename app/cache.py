import hashlib
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from urllib.parse import quote

_cache: Optional[Dict[str, Any]] = None
_directory_hash: Optional[str] = None

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
            "size": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "url": url,
            "width": width,
            "height": height,
            "aspect_ratio": aspect_ratio,
        }
    except (OSError, PermissionError):
        return None


def get_directory_mtime_hash(images_dir: Path) -> str:
    mtimes = []
    for dirpath, dirnames, _ in os.walk(images_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]
        dir_path = Path(dirpath)
        try:
            stat = dir_path.stat()
            mtimes.append((str(dir_path), stat.st_mtime))
        except OSError:
            pass
    mtimes.sort()
    hash_input = "|".join(f"{p}:{m}" for p, m in mtimes)
    return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


def get_cached_images() -> Optional[Dict[str, Any]]:
    return _cache


def is_cache_valid(images_dir: Path) -> bool:
    if _cache is None or _directory_hash is None:
        return False
    return get_directory_mtime_hash(images_dir) == _directory_hash

def save_manifest(data: Dict[str, Any]):
    global _cache
    try:
        # Include the directory hash in the manifest
        manifest_data = data.copy()
        manifest_data["_directory_hash"] = _directory_hash
        with open(MANIFEST_PATH, 'w') as f:
            json.dump(manifest_data, f, indent=2)
        _cache = data
    except Exception as e:
        print(f"Error saving manifest: {e}")

def load_manifest() -> Optional[Dict[str, Any]]:
    global _cache, _directory_hash
    if not MANIFEST_PATH.exists():
        return None
    try:
        with open(MANIFEST_PATH, 'r') as f:
            manifest_data = json.load(f)
        # Extract the actual data and the hash
        if "_directory_hash" in manifest_data:
            _directory_hash = manifest_data.pop("_directory_hash")
        _cache = manifest_data
        return manifest_data
    except Exception as e:
        print(f"Error loading manifest: {e}")
        return None

def init_manifest(images_dir: Path) -> Dict[str, Any]:
    """
    Generate the manifest by scanning the images directory.
    This is called on startup if no manifest exists, or when folders change.
    """
    global _directory_hash

    if not images_dir.exists():
        raise ValueError(f"Images directory does not exist: {images_dir}")

    # Recursively find all image files
    image_paths = [
        p for p in images_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]

    # Process images in parallel
    images = []
    aspect_ratio_counts = {}

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = executor.map(process_image_file, image_paths, [images_dir] * len(image_paths))
        for result in results:
            if result is not None:
                images.append(result)
                if result["aspect_ratio"] != "unknown":
                    aspect_ratio_counts[result["aspect_ratio"]] = aspect_ratio_counts.get(result["aspect_ratio"], 0) + 1

    # Sort images by path for consistent ordering
    images.sort(key=lambda x: x["path"])

    result = {
        "directory": str(images_dir),
        "total_images": len(images),
        "images": images,
        "aspect_ratios": aspect_ratio_counts,
    }

    # Update directory hash and save
    _directory_hash = get_directory_mtime_hash(images_dir)
    save_manifest(result)
    
    return result
