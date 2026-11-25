<div align="center">

# 📡 AirCast-AP

**Modern GTK4 + Libadwaita Wi-Fi 6 Access Point & Hotspot Manager for Linux**  
*Turn any AP-capable Linux Wi-Fi adapter (including Realtek RTL8852CU / RTL8832CU) into a fast 5 GHz Wi-Fi 6 / WPA3 hotspot with live QR sharing, NAT routing, and connected-client monitoring.*

[![GTK4 + Libadwaita](https://img.shields.io/badge/UI-GTK4_%2B_Libadwaita-4A86CF?style=for-the-badge&logo=gnome&logoColor=white)](#features)
[![Wayland Native](https://img.shields.io/badge/Wayland-Native-FFBC00?style=for-the-badge&logo=wayland&logoColor=black)](#features)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](#quick-install)
[![Companion Driver](https://img.shields.io/badge/Companion-rtl8852cu--9M2PJU--dkms-00ADD8?style=for-the-badge&logo=linux&logoColor=white)](https://github.com/9M2PJU/rtl8852cu-9M2PJU-dkms)
[![License: GPL v3](https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge)](LICENSE)

[✨ Features](#-features) •
[🪄 1-Line Install](#-1-line-interactive-install) •
[💻 CLI Usage](#-cli-usage) •
[🔌 Realtek RTL8852CU Support](#-realtek-rtl8852cu--rtl8832cu-integration) •
[☕ Support](#-support-this-project)

</div>

---

## ✨ Features

- 🎨 **Native GTK4 + Libadwaita UI** — Clean, lightweight Wayland/X11 desktop app (zero Electron bloat) with dark/light theme support and Polkit (`pkexec`) privilege prompts
- 📶 **Dual AP Backends:**
  - **`hostapd` + `dnsmasq` + `nftables`/`iptables` NAT** — Full **Wi-Fi 6 (802.11ax)**, **5 GHz 80 MHz** (ch 36 / ch 149) & **2.4 GHz**, **WPA2-PSK**, **WPA2/WPA3 Mixed**, and **WPA3-SAE**
  - **NetworkManager (`nmcli`)** — Zero-config instant hotspot fallback
- 📱 **Live Wi-Fi QR Code** — Instant scannable QR card in the GUI (and terminal `--qr` flag) that updates live as you edit SSID/passphrase
- 👥 **Connected Clients Monitor** — Live polling of connected devices (hostname, IP from DHCP leases, MAC address, RSSI signal, TX bitrate)
- ⚡ **Built-in Realtek `8852cu` Optimizer** — Automatically detects [`rtl8852cu-9M2PJU-dkms`](https://github.com/9M2PJU/rtl8852cu-9M2PJU-dkms) adapters and offers a 1-click banner to enable `rtw_he_enable=2 rtw_vht_enable=2` for full Wi-Fi 6 AP mode
- 🧹 **Clean Teardown** — Stopping the AP removes temporary NAT tables, terminates `hostapd`/`dnsmasq`, and cleanly restores your Wi-Fi interface to NetworkManager managed mode
- 💻 **Full CLI Included** — Automate or script your hotspot headlessly over SSH (`aircast-ap start|stop|status|devices`)

---

## 🪄 1-Line Interactive Install

```bash
curl -fsSL https://raw.githubusercontent.com/9M2PJU/AirCast-AP/main/install.sh | bash
```

Then launch **AirCast-AP** from your application menu (Wayland/Sway/Hyprland/GNOME/KDE) or run:

```bash
aircast-ap
```

---

## 💻 CLI Usage

```bash
# Launch GTK4 GUI
aircast-ap

# List Wi-Fi adapters & check AP / Wi-Fi 6 capabilities
aircast-ap devices

# Start a 5 GHz Wi-Fi 6 AP on wlan1 sharing internet from wlan0 (+ terminal QR)
sudo aircast-ap start -i wlan1 -s "9M2PJU-AX" -p "mypassword123" -b 5g-low -u wlan0 --qr

# Check active AP status & connected clients (or --json)
aircast-ap status

# Stop AP and restore interface to client mode
sudo aircast-ap stop

# One-command RTL8852CU Wi-Fi 6 AP module parameter setup
sudo aircast-ap tune-8852cu
```

---

## 🔌 Realtek RTL8852CU / RTL8832CU Integration

AirCast-AP works with **any** `nl80211` AP-capable Linux Wi-Fi adapter (Realtek, MediaTek, Intel, Qualcomm) and pairs seamlessly with our Linux 7.3+ DKMS driver:

👉 **[9M2PJU/rtl8852cu-9M2PJU-dkms](https://github.com/9M2PJU/rtl8852cu-9M2PJU-dkms)** — Linux 5.15–7.3+ & Clang/LLVM (CachyOS) DKMS driver for Realtek RTL8832CU & RTL8852CU USB Wi-Fi 6/6E adapters.

---

## ☕ Support This Project

If **AirCast-AP** makes Linux Wi-Fi hotspot / AP sharing effortless for you, consider supporting **9M2PJU**'s open-source & amateur radio projects:

<div align="center">

[![GitHub Sponsors](https://img.shields.io/badge/GitHub_Sponsors-9M2PJU-EA4AAA?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/9M2PJU)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy_Me_A_Coffee-9m2pju-FFDD00?style=for-the-badge&logo=buymeacoffee&logoColor=black)](https://www.buymeacoffee.com/9m2pju)
[![PayPal](https://img.shields.io/badge/PayPal-9M2PJU-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://www.paypal.com/paypalme/9M2PJU)
[![Wise](https://img.shields.io/badge/Wise-faizulz13-9FE870?style=for-the-badge&logo=wise&logoColor=black)](https://wise.com/pay/me/faizulz13)

</div>

---

## 📄 License

Licensed under the **GNU General Public License v3.0 or later** ([`LICENSE`](LICENSE)).  
*73 de 9M2PJU!* 📻
