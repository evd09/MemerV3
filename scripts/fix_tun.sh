#!/bin/bash
echo "🔧 Fixing VPN TUN Device..."

# Check if the directory exists
if [ ! -d "/dev/net" ]; then
    echo "Creating /dev/net directory..."
    sudo mkdir -p /dev/net
fi

# Create the device node if it doesn't exist
if [ ! -c "/dev/net/tun" ]; then
    echo "Creating /dev/net/tun node..."
    sudo mknod /dev/net/tun c 10 200
    sudo chmod 666 /dev/net/tun
else
    echo "✅ /dev/net/tun already exists."
fi

# Load the kernel module
echo "Loading 'tun' kernel module..."
sudo modprobe tun

echo "✅ Done! You can now run the VPN container."
