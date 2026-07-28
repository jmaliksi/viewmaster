"""
API routes
"""
from concurrent.futures import ThreadPoolExecutor
import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException, Depends, Response, Request
from fastapi.security import HTTPBearer
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Any
from app.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    BEARER_TOKEN_COOKIE_NAME,
)
from app.cache import get_cached_images, sync_manifest, regenerate_manifest, load_manifest, MANIFEST_PATH, get_images_directory

router = APIRouter(prefix="/api", tags=["api"])
security = HTTPBearer()

# Supported image extensions
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tiff", ".tif"}


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
    Return the cached image index from memory. No disk IO.
    If no manifest is loaded yet, performs an initial incremental sync.
    The directory is configured via the IMAGES_DIRECTORY environment variable (defaults to "images").

    Returns:
        Dictionary containing:
        - directory: The scanned directory path
        - total_images: Total number of images found
        - images: List of image file information
    """
    images_dir = get_images_directory()

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

    # Return from in-memory cache — no disk check on page load
    cached = get_cached_images()
    if cached is not None:
        return cached

    # No manifest loaded yet (fresh server start), do an initial sync
    try:
        result = sync_manifest(images_dir)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate image manifest: {str(e)}"
        )




@router.post("/refresh")
async def refresh_manifest(current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Incrementally refresh the manifest by comparing filesystem state.
    Stat-scans directories and only PIL-opens new/changed files.
    """
    images_dir = get_images_directory()
    try:
        result = sync_manifest(images_dir)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to refresh manifest: {str(e)}"
        )


@router.post("/regenerate")
async def regenerate_manifest_endpoint(current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Full re-scan: PIL-open every image from scratch. Nuclear option.
    """
    images_dir = get_images_directory()
    try:
        result = regenerate_manifest(images_dir)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to regenerate manifest: {str(e)}"
        )


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

    for part in decoded_parts:
        if os.path.isabs(part) or part.startswith(".."):
            raise HTTPException(status_code=400, detail="Invalid path")

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
                "Cache-Control": "public, max-age=600",
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
