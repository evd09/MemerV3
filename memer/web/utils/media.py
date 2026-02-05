"""Media processing utilities for thumbnail and waveform generation."""
import asyncio
import os
from pathlib import Path
from memer.utils.logger_setup import setup_logger

logger = setup_logger("web.media", "web.log")


async def generate_thumbnail(original_path: str) -> str:
    """Generate WebP thumbnail (300x300) from image.

    Args:
        original_path: Path to original image file

    Returns:
        Path to generated thumbnail file ({stem}_thumb.webp)

    Raises:
        Exception: If thumbnail generation fails
    """
    try:
        from PIL import Image

        p = Path(original_path)
        # Create WebP thumbnail: name_thumb.webp
        thumb_path = p.with_name(f"{p.stem}_thumb.webp")

        # Run in thread pool to avoid blocking
        def generate():
            img = Image.open(original_path)

            # Convert RGBA to RGB if needed (WebP doesn't support transparency well)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background

            # Resize maintaining aspect ratio, max 300x300
            img.thumbnail((300, 300), Image.Resampling.LANCZOS)

            # Save as WebP with quality 85
            img.save(thumb_path, 'WebP', quality=85, method=6)
            logger.info(f"Generated thumbnail: {thumb_path}")

        # Run in executor to avoid blocking event loop
        await asyncio.get_event_loop().run_in_executor(None, generate)

        return str(thumb_path)

    except Exception as e:
        logger.error(f"Thumbnail generation failed for {original_path}: {e}")
        raise


async def generate_waveform_image(audio_path: str) -> str:
    """Generate PNG waveform visualization (200x60) from audio.

    Args:
        audio_path: Path to audio file

    Returns:
        Path to generated waveform file ({stem}_wave.png)

    Raises:
        Exception: If waveform generation fails
    """
    try:
        from PIL import Image, ImageDraw
        import soundfile as sf
        import numpy as np

        def generate():
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
            logger.info(f"Generated waveform: {wave_path}")

            return str(wave_path)

        # Run in executor
        result = await asyncio.get_event_loop().run_in_executor(None, generate)
        return result

    except Exception as e:
        logger.error(f"Waveform generation failed for {audio_path}: {e}")
        raise
