#!/bin/sh
. /etc/os-release

if [ "$(id -u)" != "0" ]; then
    echo "This script must be run as root."
    exit 2
fi

# Install packages we need for our checks.
if [ "$ID" = "arch" ]; then
    pacman -Sy --needed --noconfirm --quiet jq iproute2
else
    echo "Unimplemented distro '$ID'"
    exit 1
fi

# Check network link names.
linknames=$(ip -j link show | jq -r .[].ifname)

if ! echo "$linknames" | grep -q "eth0"; then
    echo "Can't find eth0. Try booting with net.ifnames=0"
    exit 1
fi
if ! echo "$linknames" | grep -q "eth1"; then
    echo "Can't find eth1. Two NICs are required."
    exit 1
fi

# Check free space for the install bundle.
freebytes=$(df -P -B1 . | awk 'NR==2 {print $4}')
if [ "$freebytes" -lt 6442450944 ]; then
    echo "/!\ Not enough space in current directory for the install bundle, you'll need to pass --local-bundle to the script."
fi

if [ "$ID" = "arch" ]; then
    # Check free space for installs.
    freebytes=$(df -P -B1 /usr/bin | awk 'NR==2 {print $4}')
    if [ "$freebytes" -lt 650117120 ]; then
        echo "/!\ Probably not enough free space for installing dependencies (650 MiB likely required), trying anyways."
    fi
    echo "Installing dependencies..."
    pacman -Sy --needed --noconfirm --quiet python python-protobuf curl pv gnupg tar util-linux parted lvm2 e2fsprogs rpm-tools
else
    echo "Unimplemented distro '$ID'"
    exit 1
fi