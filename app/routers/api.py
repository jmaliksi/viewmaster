"""
API routes
"""
import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote, unquote
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Any
from app.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)

router = APIRouter(prefix="/api", tags=["api"])
security = HTTPBearer()

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


# Authentication models
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


@router.post("/login", response_model=TokenResponse)
async def login(login_data: LoginRequest):
    """Login endpoint - returns JWT token"""
    user = authenticate_user(login_data.username, login_data.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


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
async def load_images(current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Recursively scan the configured images directory and return an index of all images.
    The directory is configured via the IMAGES_DIRECTORY environment variable (defaults to "images").
    
    Returns:
        Dictionary containing:
        - directory: The scanned directory path
        - total_images: Total number of images found
        - images: List of image file information
    """
    print(current_user)
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


@router.get("/images/{image_path:path}")
async def serve_image(image_path: str, current_user: dict = Depends(get_current_user)):
    """
    Serve an image file. Requires authentication.
    The image_path should be URL-encoded path segments.
    """
    images_dir = get_images_directory()
    
    # Decode URL-encoded path parts
    path_parts = image_path.split("/")
    decoded_parts = [unquote(part) for part in path_parts]
    
    # Construct the full file path
    image_file = images_dir / "/".join(decoded_parts)
    
    # Security check: ensure the file is within the images directory
    try:
        image_file.resolve().relative_to(images_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Check if file exists and is an image
    if not image_file.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    
    if image_file.suffix.lower() not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Not an image file")
    
    # Determine content type based on extension
    content_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }
    
    content_type = content_type_map.get(image_file.suffix.lower(), "image/jpeg")
    
    return FileResponse(
        str(image_file),
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=3600"}
    )