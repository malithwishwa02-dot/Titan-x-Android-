#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Install Ubuntu 22.04 from OVH Rescue Mode
# Run this INSIDE the rescue SSH session on 51.68.33.34
#
# This script:
#   1. Partitions the primary disk
#   2. Installs Ubuntu 22.04 via debootstrap
#   3. Configures networking, SSH, GRUB
#   4. Sets root password
#   5. Reboots into the installed system
#
# Usage (from rescue mode):
#   curl -sL https://raw.githubusercontent.com/.../rescue_install_ubuntu.sh | bash
#   OR: copy-paste and run
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

DISK="/dev/sda"
HOSTNAME="titan-ks4"
IP="51.68.33.34"

log() { echo -e "\n\033[1;36m══ $1\033[0m"; }

# ─── Detect disk ────────────────────────────────────────────────────
if [ -b /dev/nvme0n1 ]; then
  DISK="/dev/nvme0n1"
  PART1="${DISK}p1"
  PART2="${DISK}p2"
  PART3="${DISK}p3"
elif [ -b /dev/sda ]; then
  DISK="/dev/sda"
  PART1="${DISK}1"
  PART2="${DISK}2"
  PART3="${DISK}3"
else
  echo "ERROR: No disk found!"
  lsblk
  exit 1
fi

log "Using disk: $DISK"
lsblk "$DISK"

# ─── Phase 1: Partition ────────────────────────────────────────────
log "Phase 1: Partitioning $DISK"

# Wipe existing partitions
wipefs -af "$DISK"
sgdisk --zap-all "$DISK"

# Create GPT partitions:
#   1: 512M EFI System Partition
#   2: 2G swap
#   3: rest → ext4 root
sgdisk -n 1:0:+512M -t 1:EF00 -c 1:"EFI" "$DISK"
sgdisk -n 2:0:+2G   -t 2:8200 -c 2:"swap" "$DISK"
sgdisk -n 3:0:0     -t 3:8300 -c 3:"root" "$DISK"
partprobe "$DISK"
sleep 2

log "Formatting partitions..."
mkfs.fat -F32 "$PART1"
mkswap "$PART2"
mkfs.ext4 -F "$PART3"

# ─── Phase 2: Mount and debootstrap ────────────────────────────────
log "Phase 2: Installing Ubuntu 22.04 (debootstrap)"

apt-get update -qq
apt-get install -y -qq debootstrap arch-install-scripts

mount "$PART3" /mnt
mkdir -p /mnt/boot/efi
mount "$PART1" /mnt/boot/efi

debootstrap --arch=amd64 jammy /mnt http://archive.ubuntu.com/ubuntu

# ─── Phase 3: Configure the installed system ───────────────────────
log "Phase 3: Configuring system"

# Mount virtual filesystems
mount --bind /dev  /mnt/dev
mount --bind /dev/pts /mnt/dev/pts
mount --bind /proc /mnt/proc
mount --bind /sys  /mnt/sys
mount --bind /sys/firmware/efi/efivars /mnt/sys/firmware/efi/efivars 2>/dev/null || true

# fstab
cat > /mnt/etc/fstab << FSTAB
$PART3  /          ext4  errors=remount-ro  0 1
$PART1  /boot/efi  vfat  umask=0077         0 1
$PART2  none       swap  sw                 0 0
FSTAB

# hostname
echo "$HOSTNAME" > /mnt/etc/hostname
cat > /mnt/etc/hosts << HOSTS
127.0.0.1   localhost
127.0.1.1   $HOSTNAME
$IP         $HOSTNAME
HOSTS

# Network — detect current gateway and interface from rescue
GATEWAY=$(ip route | awk '/default/{print $3}')
IFACE=$(ip route | awk '/default/{print $5}')

cat > /mnt/etc/netplan/01-netcfg.yaml << NETPLAN
network:
  version: 2
  renderer: networkd
  ethernets:
    ${IFACE}:
      addresses:
        - ${IP}/24
      routes:
        - to: default
          via: ${GATEWAY}
      nameservers:
        addresses:
          - 213.186.33.99
          - 8.8.8.8
NETPLAN

# APT sources
cat > /mnt/etc/apt/sources.list << APT
deb http://archive.ubuntu.com/ubuntu jammy main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu jammy-updates main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu jammy-security main restricted universe multiverse
APT

# chroot: install kernel, GRUB, SSH, essential packages
chroot /mnt /bin/bash -c "
apt-get update
apt-get install -y linux-image-generic linux-headers-generic \
  grub-efi-amd64 efibootmgr \
  openssh-server sudo curl wget rsync \
  systemd-sysv locales

# Locale
locale-gen en_US.UTF-8

# GRUB
grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=ubuntu --recheck
update-grub

# Enable SSH
systemctl enable ssh

# Set root password
echo 'root:TitanKS4-2026!' | chpasswd

# Allow root SSH login with password (temporary)
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
"

# Copy SSH authorized_keys from rescue
mkdir -p /mnt/root/.ssh
cp /root/.ssh/authorized_keys /mnt/root/.ssh/ 2>/dev/null || true
chmod 700 /mnt/root/.ssh
chmod 600 /mnt/root/.ssh/authorized_keys 2>/dev/null || true

# ─── Phase 4: Cleanup and reboot ───────────────────────────────────
log "Phase 4: Cleanup"

umount /mnt/sys/firmware/efi/efivars 2>/dev/null || true
umount /mnt/sys
umount /mnt/proc
umount /mnt/dev/pts
umount /mnt/dev
umount /mnt/boot/efi
umount /mnt

log "✅ Ubuntu 22.04 installed successfully!"
echo ""
echo "  Root password: TitanKS4-2026!"
echo "  IP: $IP"
echo ""
echo "  Next steps:"
echo "    1. Set boot to harddisk via OVH API"
echo "    2. Reboot the server"
echo "    3. SSH root@$IP (password: TitanKS4-2026!)"
echo "    4. Run: bash /opt/titan-v11.3-device/scripts/setup_ovh_desktop.sh"
echo ""
