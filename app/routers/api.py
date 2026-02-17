"""
API routes
"""
import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote, unquote
from fastapi import APIRouter, HTTPException, Depends, Response, Request
from fastapi.security import HTTPBearer
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Any
from PIL import Image
from app.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    BEARER_TOKEN_COOKIE_NAME,
)

router = APIRouter(prefix="/api", tags=["api"])
security = HTTPBearer()

# Supported image extensions
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tiff", ".tif"}

# Common aspect ratios to map to
COMMON_ASPECT_RATIOS = ["1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16"]

# Aspect ratio mapping thresholds (normalized: larger/smaller dimension)
ASPECT_RATIO_MAP = [
    (1.15, "1:1"),    # <= 1.15 -> 1:1 (square-ish)
    (1.4, "4:3"),    # <= 1.4 -> 4:3 (standard)
    (1.6, "3:2"),    # <= 1.6 -> 3:2 (classic photo)
    (1.9, "16:9"),   # <= 1.9 -> 16:9 (widescreen)
    (float('inf'), "2:3"),   # > 1.9 -> 2:3 (portrait)
]

def get_aspect_ratio(width: int, height: int) -> str:
    if width == 0 or height == 0:
        return "unknown"

    # Determine if landscape or portrait
    is_landscape = width >= height

    # Normalize ratio so we always compare consistently
    if is_landscape:
        ratio = width / height
    else:
        ratio = height / width

    for threshold, ratio_str in ASPECT_RATIO_MAP:
        if ratio <= threshold:
            # For portrait images (taller than wide), invert the ratio string
            if not is_landscape and ratio_str != "1:1":
                parts = ratio_str.split(':')
                return f"{parts[1]}:{parts[0]}"
            return ratio_str

    return "unknown"

# Skip SVG and ICO for aspect ratio detection (not supported by PIL)
ASPECT_RATIO_SKIP_EXTENSIONS = {".svg", ".ico"}

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
async def login(login_data: LoginRequest, response: Response):
    """
    Login endpoint - returns JWT token.
    Sets the token as an HTTP-only cookie for security.
    Also returns the token in the response body for compatibility.
    """
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

    # Set token as HTTP-only cookie for security (prevents XSS attacks)
    # Calculate max_age in seconds (same as token expiration)
    max_age_seconds = int(access_token_expires.total_seconds())
    response.set_cookie(
        key=BEARER_TOKEN_COOKIE_NAME,
        value=access_token,
        max_age=max_age_seconds,
        httponly=True,  # Prevents JavaScript access (security)
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",  # CSRF protection
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
async def logout(response: Response):
    """
    Logout endpoint - clears the authentication cookie.
    """
    # Clear the cookie by setting it with an expired date
    response.delete_cookie(
        key=BEARER_TOKEN_COOKIE_NAME,
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
    )
    return {"message": "Successfully logged out"}


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


@router.get("/me")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """
    Get current authenticated user information.
    Lightweight endpoint for checking authentication status.
    """
    return {
        "username": current_user.get("username"),
        "authenticated": True,
    }


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
    aspect_ratio_counts: Dict[str, int] = {}

    for image_path in images_dir.rglob("*"):
        if image_path.is_file() and image_path.suffix.lower() in IMAGE_EXTENSIONS:
            try:
                stat = image_path.stat()
                # Get relative path from the images directory
                relative_path = image_path.relative_to(images_dir)

                # Build URL path for the image (URL encode each part of the path)
                url_path_parts = ["/api/images"] + [quote(part) for part in relative_path.parts]
                url = "/".join(url_path_parts)

                # Calculate aspect ratio using PIL (skip for unsupported formats)
                width = 0
                height = 0
                aspect_ratio = "unknown"

                if image_path.suffix.lower() not in ASPECT_RATIO_SKIP_EXTENSIONS:
                    try:
                        with Image.open(image_path) as img:
                            width, height = img.size
                            aspect_ratio = get_aspect_ratio(width, height)
                    except Exception:
                        pass  # Keep unknown if we can't read dimensions

                # Track aspect ratio counts
                if aspect_ratio != "unknown":
                    aspect_ratio_counts[aspect_ratio] = aspect_ratio_counts.get(aspect_ratio, 0) + 1

                images.append({
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
        "aspect_ratios": aspect_ratio_counts,
    }


@router.get("/images/{image_path:path}")
async def serve_image(
    image_path: str,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    Serve an image file with ETag support for efficient caching.
    Requires authentication.
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

    # Get file metadata for ETag generation
    stat = image_file.stat()

    # Generate ETag from file modification time and size
    # This ensures ETag changes when file is updated or replaced
    etag = f'"{stat.st_mtime}-{stat.st_size}"'

    # Check If-None-Match header for conditional request
    if_none_match = request.headers.get("If-None-Match")
    if if_none_match == etag:
        # File hasn't changed - return 304 Not Modified
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": "public, max-age=31536000, immutable",
            }
        )

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

    # Return file with ETag and improved cache headers
    # Using immutable cache since images don't change once loaded
    return FileResponse(
        str(image_file),
        media_type=content_type,
        headers={
            "ETag": etag,
            "Cache-Control": "public, max-age=31536000, immutable",
        }
    )