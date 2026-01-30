import os, time

LOG_FOLDER = "logs"
MAX_AGE_DAYS = 7
MAX_SIZE_MB = 5

def cleanup_logs():
    now = time.time()
    with os.scandir(LOG_FOLDER) as entries:
        for entry in entries:
            if not entry.is_file():
                continue
            stats = entry.stat()
            age = now - stats.st_mtime
            size_mb = stats.st_size / (1024 * 1024)
            if age > MAX_AGE_DAYS * 86400 or size_mb > MAX_SIZE_MB:
                print(f"🧹 Deleting: {entry.name}")
                os.remove(entry.path)

if __name__ == "__main__":
    cleanup_logs()
