"""
API routes
"""
import os
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any

router = APIRouter(prefix="/api", tags=["api"])

# Supported image extensions
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tiff", ".tif"}

# Get images directory from environment variable, default to "images"
IMAGES_DIRECTORY = os.getenv("IMAGES_DIRECTORY", "images")


def get_images_directory() -> Path:
    """Resolve the images directory path from environment variable"""
    project_root = Path(__file__).parent.parent.parent
    images_dir_str = IMAGES_DIRECTORY
    if os.path.isabs(images_dir_str):
        return Path(images_dir_str)
    else:
        return project_root / images_dir_str


@router.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Welcome to ViewMaster API",
        "version": "1.0.0"
    }


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@router.get("/load")
async def load_images() -> Dict[str, Any]:
    """
    Recursively scan the configured images directory and return an index of all images.
    The directory is configured via the IMAGES_DIRECTORY environment variable (defaults to "images").
    
    Returns:
        Dictionary containing:
        - directory: The scanned directory path
        - total_images: Total number of images found
        - images: List of image file information
    """
    # Resolve the images directory path
    images_dir = get_images_directory()
    
    # Check if directory exists
    if not images_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Configured images directory '{images_dir}' does not exist"
        )
    
    if not images_dir.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Configured images path '{images_dir}' is not a directory"
        )
    
    # Recursively find all image files
    images: List[Dict[str, Any]] = []
    
    for image_path in images_dir.rglob("*"):
        if image_path.is_file() and image_path.suffix.lower() in IMAGE_EXTENSIONS:
            try:
                stat = image_path.stat()
                # Get relative path from the images directory
                relative_path = image_path.relative_to(images_dir)
                
                # Build URL path for the image (URL encode each part of the path)
                url_path_parts = ["/api/images"] + [quote(part) for part in relative_path.parts]
                url = "/".join(url_path_parts)
                
                images.append({
                    "path": str(relative_path),
                    "full_path": str(image_path),
                    "relative_path": str(relative_path),
                    "filename": image_path.name,
                    "extension": image_path.suffix.lower(),
                    "size": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "url": url,
                })
            except (OSError, PermissionError) as e:
                # Skip files that can't be accessed
                continue
    
    # Sort images by path for consistent ordering
    images.sort(key=lambda x: x["path"])
    
    return {
        "directory": str(images_dir),
        "total_images": len(images),
        "images": images,
    }