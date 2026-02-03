#!/usr/bin/env python3
"""
Generate WebP thumbnails for existing sound images
Run this after deploying the thumbnail optimization
"""

import os
from pathlib import Path
from PIL import Image

SOUND_FOLDER = Path(__file__).parent.parent / "sounds"

def generate_thumbnail(image_path):
    """Generate 300x300 WebP thumbnail"""
    try:
        img = Image.open(image_path)
        
        # Convert RGBA to RGB if needed
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1])
            else:
                background.paste(img)
            img = background
        
        # Resize maintaining aspect ratio, max 300x300
        img.thumbnail((300, 300), Image.Resampling.LANCZOS)
        
        # Save as WebP
        thumb_path = image_path.with_name(f"{image_path.stem}_thumb.webp")
        img.save(thumb_path, 'WebP', quality=85, method=6)
        
        print(f"✓ Generated {thumb_path.name} ({thumb_path.stat().st_size} bytes)")
        return True
        
    except Exception as e:
        print(f"✗ Failed to generate thumbnail for {image_path.name}: {e}")
        return False

def main():
    if not SOUND_FOLDER.exists():
        print(f"Error: Sound folder not found: {SOUND_FOLDER}")
        return
    
    print(f"Scanning {SOUND_FOLDER} for images...")
    
    image_extensions = {'.png', '.jpg', '.jpeg', '.gif'}
    images = []
    
    for file in SOUND_FOLDER.iterdir():
        if file.suffix.lower() in image_extensions and '_thumb' not in file.stem:
            images.append(file)
    
    if not images:
        print("No images found to process.")
        return
    
    print(f"Found {len(images)} images. Generating thumbnails...\n")
    
    success_count = 0
    for img_path in images:
        if generate_thumbnail(img_path):
            success_count += 1
    
    print(f"\n✓ Generated {success_count}/{len(images)} thumbnails")

if __name__ == "__main__":
    main()
