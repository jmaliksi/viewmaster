import hashlib
import os
from pathlib import Path
from typing import Optional, Dict, Any

_cache: Optional[Dict[str, Any]] = None
_directory_hash: Optional[str] = None


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


def cache_images(data: Dict[str, Any], images_dir: Path):
    global _cache, _directory_hash
    _cache = data
    _directory_hash = get_directory_mtime_hash(images_dir)


def is_cache_valid(images_dir: Path) -> bool:
    if _cache is None or _directory_hash is None:
        return False
    return get_directory_mtime_hash(images_dir) == _directory_hash
