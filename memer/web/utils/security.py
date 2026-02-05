"""File security and validation utilities."""
import os
import re

# Allowed file extensions for uploads
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'ogg', 'opus', 'png', 'jpg', 'jpeg', 'gif', 'webp'}


def sanitize_filename(filename: str) -> str:
    """Remove unsafe characters from filename.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename with only alphanumeric, dots, underscores, and hyphens

    Example:
        >>> sanitize_filename("hello world!.mp3")
        "helloworld.mp3"
    """
    # Keep only alphanumeric, dashes, underscores, and dots
    clean = "".join(c for c in filename if c.isalnum() or c in "-_.")
    return clean


def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed.

    Args:
        filename: Filename to check

    Returns:
        True if file extension is in ALLOWED_EXTENSIONS, False otherwise

    Example:
        >>> allowed_file("sound.mp3")
        True
        >>> allowed_file("malware.exe")
        False
    """
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def validate_sound_path(sound_folder: str, filename: str) -> str:
    """Validate and return safe path to sound file.

    Args:
        sound_folder: Base sound folder path
        filename: Filename (will be sanitized)

    Returns:
        Absolute path to sound file

    Raises:
        ValueError: If path traversal detected or path is outside sound folder

    Example:
        >>> validate_sound_path("/sounds", "test.mp3")
        "/sounds/test.mp3"
        >>> validate_sound_path("/sounds", "../etc/passwd")
        ValueError: Invalid path
    """
    safe_name = sanitize_filename(filename)
    path = os.path.join(sound_folder, safe_name)

    # Prevent directory traversal
    if not os.path.abspath(path).startswith(os.path.abspath(sound_folder)):
        raise ValueError("Invalid path: directory traversal detected")

    return path


def validate_image_extension(filename: str) -> bool:
    """Check if file is a valid image type.

    Args:
        filename: Filename to check

    Returns:
        True if extension is png, jpg, jpeg, or gif

    Example:
        >>> validate_image_extension("avatar.png")
        True
        >>> validate_image_extension("sound.mp3")
        False
    """
    if '.' not in filename:
        return False

    ext = filename.rsplit('.', 1)[1].lower()
    return ext in {'png', 'jpg', 'jpeg', 'gif'}


def validate_audio_extension(filename: str) -> bool:
    """Check if file is a valid audio type.

    Args:
        filename: Filename to check

    Returns:
        True if extension is mp3, wav, ogg, or opus

    Example:
        >>> validate_audio_extension("sound.mp3")
        True
        >>> validate_audio_extension("image.png")
        False
    """
    if '.' not in filename:
        return False

    ext = filename.rsplit('.', 1)[1].lower()
    return ext in {'mp3', 'wav', 'ogg', 'opus'}
