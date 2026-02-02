import os
import subprocess
from pathlib import Path

# Constants
SOUND_FOLDER = "sounds"
EXTS = {".mp3", ".wav", ".m4a"}

def convert_to_opus():
    print(f"🎵 Scanning {SOUND_FOLDER} for audio files...")
    count = 0
    errors = 0
    
    for file in Path(SOUND_FOLDER).glob("*"):
        if file.suffix.lower() in EXTS:
            target = file.with_suffix(".opus")
            
            # Skip if already exists
            if target.exists():
                continue
                
            print(f"➡️ Converting {file.name} -> {target.name}...")
            
            # ffmpeg command: -y (overwrite), -ac 2 (stereo), -b:a 96k (bitrate)
            cmd = [
                "ffmpeg", "-y", "-i", str(file), 
                "-c:a", "libopus", "-b:a", "96k", 
                "-ac", "2", "-v", "error", str(target)
            ]
            
            try:
                subprocess.run(cmd, check=True)
                count += 1
            except subprocess.CalledProcessError as e:
                print(f"❌ Failed to convert {file.name}: {e}")
                errors += 1
                
    print(f"\n✅ Done! Converted {count} files. Errors: {errors}")

if __name__ == "__main__":
    if not os.path.exists(SOUND_FOLDER):
        print(f"❌ '{SOUND_FOLDER}' directory not found!")
    else:
        convert_to_opus()
