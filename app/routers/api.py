"""
API routes
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Welcome to ViewMaster API",
        "docs": "/docs",
        "version": "1.0.0"
    }


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}