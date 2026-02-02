#!/bin/bash
# install_ffmpeg.sh

echo "Detecting OS..."
if [ -f /etc/debian_version ]; then
    echo "Debian/Ubuntu detected."
    sudo apt-get update
    sudo apt-get install -y ffmpeg
elif [ -f /etc/redhat-release ]; then
    echo "RedHat/CentOS detected."
    sudo yum install -y ffmpeg
elif [ -f /etc/arch-release ]; then
    echo "Arch Linux detected."
    sudo pacman -S --noconfirm ffmpeg
else
    echo "Unknown OS. Please install ffmpeg manually."
    exit 1
fi

echo "✅ ffmpeg installed successfully!"
ffmpeg -version
