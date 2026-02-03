#!/usr/bin/env python3
"""
Generate waveform PNGs for existing audio files in the sounds directory.
Run this after deploying V3.3.0 to generate waveforms for all existing sounds.

Usage:
    python scripts/generate_waveforms.py
    
or in Docker:
    docker compose exec memerbot python scripts/generate_waveforms.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from memer.config import SOUND_FOLDER, AUDIO_EXTS

async def generate_waveform(audio_path):
    """Generate waveform PNG from audio file (same logic as webbox.py)"""
    from PIL import Image, ImageDraw
    import soundfile as sf
    import numpy as np
    
    def gen():
        try:
            # Read audio file
            data, samplerate = sf.read(audio_path)
            
            # Convert stereo to mono
            if len(data.shape) > 1:
                data = data.mean(axis=1)
            
            # Waveform dimensions
            width, height = 200, 60
            samples = width
            
            # Downsample audio data
            chunk_size = max(1, len(data) // samples)
            
            waveform = []
            for i in range(samples):
                start = i * chunk_size
                end = min(start + chunk_size, len(data))
                chunk = data[start:end]
                
                if len(chunk) > 0:
                    min_val = float(chunk.min())
                    max_val = float(chunk.max())
                    waveform.append((min_val, max_val))
                else:
                    waveform.append((0.0, 0.0))
            
            # Create image with transparency
            img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            # Draw waveform bars
            for i, (min_val, max_val) in enumerate(waveform):
                # Normalize to image height
                y_min = int((1 + min_val) * height / 2)
                y_max = int((1 + max_val) * height / 2)
                
                # Clamp values
                y_min = max(0, min(height - 1, y_min))
                y_max = max(0, min(height - 1, y_max))
                
                # Draw vertical line (white with alpha)
                if y_max > y_min:
                    draw.line([(i, y_min), (i, y_max)], 
                             fill=(255, 255, 255, 180), width=1)
                else:
                    # Draw at least 1 pixel for silence
                    draw.point((i, height // 2), fill=(255, 255, 255, 120))
            
            # Save as optimized PNG
            wave_path = Path(audio_path).with_name(f"{Path(audio_path).stem}_wave.png")
            img.save(wave_path, 'PNG', optimize=True)
            
            # Check file size
            size_kb = wave_path.stat().st_size / 1024
            return wave_path.name, size_kb
            
        except Exception as e:
            raise Exception(f"Waveform generation failed: {e}")
    
    # Run in executor
    result = await asyncio.get_event_loop().run_in_executor(None, gen)
    return result

async def main():
    print("=" * 60)
    print("Waveform PNG Generation Script - V3.3.0")
    print("=" * 60)
    
    sound_dir = Path(SOUND_FOLDER)
    if not sound_dir.exists():
        print(f"❌ Sound directory not found: {SOUND_FOLDER}")
        return
    
    # Find all audio files
    audio_files = []
    for ext in AUDIO_EXTS:
        audio_files.extend(sound_dir.glob(f"*{ext}"))
    
    audio_files = sorted(audio_files, key=lambda f: f.name.lower())
    
    print(f"\nFound {len(audio_files)} audio files\n")
    
    total = len(audio_files)
    generated = 0
    skipped = 0
    failed = 0
    total_size_kb = 0
    
    for i, audio_file in enumerate(audio_files, 1):
        wave_file = audio_file.with_name(f"{audio_file.stem}_wave.png")
        
        # Progress
        progress = f"[{i}/{total}]"
        
        if wave_file.exists():
            size_kb = wave_file.stat().st_size / 1024
            print(f"{progress} ⊘ Skip: {audio_file.name:40} (exists, {size_kb:.1f} KB)")
            skipped += 1
            continue
        
        try:
            filename, size_kb = await generate_waveform(audio_file)
            print(f"{progress} ✓ Generated: {audio_file.name:40} → {size_kb:.1f} KB")
            generated += 1
            total_size_kb += size_kb
        except Exception as e:
            print(f"{progress} ✗ Failed: {audio_file.name:40} - {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Total audio files:   {total}")
    print(f"Generated:           {generated}")
    print(f"Skipped (existing):  {skipped}")
    print(f"Failed:              {failed}")
    
    if generated > 0:
        avg_size_kb = total_size_kb / generated
        print(f"\nAverage waveform size: {avg_size_kb:.2f} KB")
        print(f"Total new waveforms:   {total_size_kb:.2f} KB ({total_size_kb / 1024:.2f} MB)")
    
    print("\n✅ Waveform generation complete!")

if __name__ == "__main__":
    asyncio.run(main())
