import os
import asyncio
from pathlib import Path

# Config
SOUND_FOLDER = "/app/sounds"
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif'}

async def generate_thumb(path):
    p = Path(path)
    # Skip existing thumbs
    if "_thumb" in p.stem: 
        return
    
    thumb_path = p.with_name(f"{p.stem}_thumb{p.suffix}")
    
    if thumb_path.exists():
        # print(f"Skipping {p.name}, thumb exists.")
        return

    print(f"Generating thumb for {p.name} -> {thumb_path.name}")
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(p),
            "-vf", "scale=200:-1",
            "-v", "error", str(thumb_path)
        )
        await proc.wait()
    except Exception as e:
        print(f"Error converting {p.name}: {e}")

async def main():
    if not os.path.exists(SOUND_FOLDER):
        print(f"Sound folder {SOUND_FOLDER} not found.")
        return

    # Gather all images
    files = [f for f in Path(SOUND_FOLDER).iterdir() if f.suffix.lower() in EXTENSIONS]
    print(f"Scanning {len(files)} files in {SOUND_FOLDER}...")
    
    tasks = []
    generated_count = 0
    
    for f in files:
        if "_thumb" not in f.stem:
            tasks.append(generate_thumb(f))

    print(f"Found {len(tasks)} images needing thumbnails.")

    # Run in chunks to avoid CPU checks
    chunk_size = 10
    for i in range(0, len(tasks), chunk_size):
        chunk = tasks[i:i+chunk_size]
        await asyncio.gather(*chunk)
        print(f"Processed {min(i+chunk_size, len(tasks))}/{len(tasks)}")

    print("Thumbnail generation complete.")

if __name__ == "__main__":
    asyncio.run(main())
