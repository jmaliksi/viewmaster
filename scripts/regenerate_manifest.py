#!/usr/bin/env python3
"""
Script to manually regenerate the manifest.json file.
Usage: python scripts/regenerate_manifest.py
"""
import sys
import os

# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.cache import regenerate_manifest, get_images_directory

def main():
    try:
        images_dir = get_images_directory()
        print(f"Regenerating manifest for directory: {images_dir}")

        if not images_dir.exists():
            print(f"Error: Images directory does not exist: {images_dir}")
            sys.exit(1)

        if not images_dir.is_dir():
            print(f"Error: Path is not a directory: {images_dir}")
            sys.exit(1)

        result = regenerate_manifest(images_dir)
        print(f"Successfully regenerated manifest with {result['total_images']} images")
        print(f"Manifest saved to: {project_root}/manifest.json")

    except Exception as e:
        print(f"Error regenerating manifest: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
