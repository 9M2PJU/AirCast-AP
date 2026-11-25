#!/usr/bin/env bash
# ==============================================================================
# AirCast-AP - Interactive 1-Line Installer
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/9M2PJU/AirCast-AP/main/install.sh | bash
# ==============================================================================
set -euo pipefail

REPO_URL="https://github.com/9M2PJU/AirCast-AP.git"
INSTALL_DIR="${HOME}/.local/share/aircast-ap"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"

BOLD='\033[1m' DIM='\033[2m' CYAN='\033[1;36m' GREEN='\033[1;32m' YELLOW='\033[1;33m' RESET='\033[0m'
info() { printf "${CYAN}ℹ${RESET}  %b\n" "$*"; }
ok()   { printf "${GREEN}✓${RESET}  %b\n" "$*"; }
warn() { printf "${YELLOW}⚠${RESET}  %b\n" "$*"; }

prompt_yn() {
    local q="$1" def="${2:-y}" ans hint
    hint=$([ "$def" = "y" ] && echo "[Y/n]" || echo "[y/N]")
    while true; do
        printf "${BOLD}?${RESET}  %s ${DIM}%s${RESET} " "$q" "$hint" > /dev/tty
        IFS= read -r ans < /dev/tty || ans=""
        ans="${ans:-$def}"
        case "${ans,,}" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
        esac
    done
}

printf "\n${CYAN}╭──────────────────────────────────────────────────────────────╮${RESET}\n"
printf "${CYAN}│${RESET}  ${BOLD}📡 AirCast-AP - Linux Wi-Fi 6 AP Manager Installer${RESET}          ${CYAN}│${RESET}\n"
printf "${CYAN}│${RESET}  ${DIM}GTK4 + Libadwaita Native Wayland App & CLI • by 9M2PJU${RESET}      ${CYAN}│${RESET}\n"
printf "${CYAN}╰──────────────────────────────────────────────────────────────╯${RESET}\n\n"

DISTRO_ID="unknown"
[ -r /etc/os-release ] && . /etc/os-release && DISTRO_ID="${ID:-unknown}"

if prompt_yn "Install/verify system dependencies (GTK4, Libadwaita, hostapd, dnsmasq, python-qrcode)?" "y"; then
    if command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --needed --noconfirm python python-gobject gtk4 libadwaita hostapd dnsmasq iw qrencode python-qrcode python-pillow
    elif command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 hostapd dnsmasq iw qrencode python3-qrcode python3-pil policykit-1
        sudo systemctl stop hostapd dnsmasq 2>/dev/null || true
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3 python3-gobject gtk4 libadwaita hostapd dnsmasq iw qrencode python3-qrcode python3-pillow
    else
        warn "Unknown package manager (${DISTRO_ID}). Make sure python3, gtk4, libadwaita, hostapd, dnsmasq, and iw are installed."
    fi
fi

mkdir -p "$(dirname "$INSTALL_DIR")" "$BIN_DIR" "$APP_DIR"
if [ -d "${INSTALL_DIR}/.git" ]; then
    info "Updating ${INSTALL_DIR}..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    info "Cloning AirCast-AP into ${INSTALL_DIR}..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

cat > "${BIN_DIR}/aircast-ap" <<EOF
#!/usr/bin/env bash
PYTHONPATH="${INSTALL_DIR}\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m aircast_ap.cli "\$@"
EOF
chmod +x "${BIN_DIR}/aircast-ap"

mkdir -p "${HOME}/.local/share/icons/hicolor/scalable/apps" "${HOME}/.local/share/icons/hicolor/256x256/apps"
cp "${INSTALL_DIR}/data/icons/my.hamradio.AirCastAP.svg" "${HOME}/.local/share/icons/hicolor/scalable/apps/"
cp "${INSTALL_DIR}/data/icons/aircast-ap-logo.png" "${HOME}/.local/share/icons/hicolor/256x256/apps/my.hamradio.AirCastAP.png"
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true

sed "s|^Exec=.*|Exec=${BIN_DIR}/aircast-ap gui|" "${INSTALL_DIR}/data/aircast-ap.desktop" > "${APP_DIR}/aircast-ap.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" 2>/dev/null || true

ok "Installed launcher: ${BIN_DIR}/aircast-ap"
ok "Installed desktop entry: ${APP_DIR}/aircast-ap.desktop"
printf "\n${GREEN}${BOLD}Done!${RESET} Launch from your app menu or run: ${BOLD}aircast-ap${RESET}\n"
printf "${DIM}CLI help: aircast-ap --help • 73 de 9M2PJU 📻${RESET}\n\n"
