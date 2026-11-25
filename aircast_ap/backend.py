#!/usr/bin/env python3
"""AirCast-AP - Core AP backend (interface discovery, hostapd/dnsmasq/NAT, nmcli, client stats)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

STATE_DIR = Path("/run/aircast-ap")
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "aircast-ap"
CONFIG_FILE = CONFIG_DIR / "config.json"
NM_CON_NAME = "AirCast-AP"
AP_SUBNET = "10.42.99"
AP_IP = f"{AP_SUBNET}.1"


@dataclass
class APConfig:
    iface: str = ""
    ssid: str = "AirCast-AX"
    password: str = "aircast1234"
    band: str = "5g-low"  # 5g-low (ch36), 5g-high (ch149), 2g (ch6)
    channel: int = 36
    width: str = "80"  # 20, 40, 80
    country: str = "MY"
    security: str = "wpa2"  # wpa2, wpa2-wpa3, wpa3
    backend: str = "hostapd"  # hostapd, nmcli
    share_internet: bool = True
    upstream: str = ""
    wifi6: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def load(cls) -> "APConfig":
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text())
                valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                return cls(**valid)
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.to_dict(), indent=2))
        try:
            CONFIG_FILE.chmod(0o600)
        except OSError:
            pass


@dataclass
class WifiInterface:
    name: str
    driver: str
    mac: str
    ap_supported: bool
    wifi6_ap: bool
    state: str

    @property
    def label(self) -> str:
        tags = []
        if self.driver in ("rtl8852cu", "8852cu", "rtw89_8852cu"):
            tags.append("8852CU")
        elif self.driver:
            tags.append(self.driver)
        if self.wifi6_ap:
            tags.append("Wi-Fi 6")
        elif self.ap_supported:
            tags.append("AP")
        tag_str = f" ({', '.join(tags)})" if tags else ""
        return f"{self.name}{tag_str}"


def _run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def list_wifi_interfaces() -> list[WifiInterface]:
    result: list[WifiInterface] = []
    net_dir = Path("/sys/class/net")
    if not net_dir.exists():
        return result

    for entry in sorted(net_dir.iterdir()):
        if not (entry / "wireless").exists() and not (entry / "phy80211").exists():
            continue
        name = entry.name
        driver = ""
        drv_link = entry / "device" / "driver"
        if drv_link.exists():
            driver = drv_link.resolve().name
        mac = (entry / "address").read_text().strip() if (entry / "address").exists() else ""
        state = (entry / "operstate").read_text().strip() if (entry / "operstate").exists() else "unknown"

        ap_supported = False
        wifi6_ap = False
        phy_name_file = entry / "phy80211" / "name"
        if phy_name_file.exists() and shutil.which("iw"):
            phy = phy_name_file.read_text().strip()
            iw_out = _run(["iw", "phy", phy, "info"]).stdout
            if re.search(r"^\s*\*\s+AP\s*$", iw_out, re.MULTILINE):
                ap_supported = True
            if "HE Iftypes:" in iw_out and "AP" in iw_out.split("HE Iftypes:", 1)[1].splitlines()[0]:
                wifi6_ap = True

        result.append(
            WifiInterface(
                name=name,
                driver=driver,
                mac=mac,
                ap_supported=ap_supported,
                wifi6_ap=wifi6_ap,
                state=state,
            )
        )

    # Prefer Realtek 8852CU / Wi-Fi 6 AP adapters first
    result.sort(
        key=lambda x: (
            0 if x.driver in ("rtl8852cu", "8852cu", "rtw89_8852cu") else 1,
            0 if x.wifi6_ap else 1,
            0 if x.ap_supported else 1,
            x.name,
        )
    )
    return result


def list_upstream_interfaces(exclude: str = "") -> list[str]:
    ifaces: list[str] = []
    default_dev = detect_default_upstream()
    if default_dev and default_dev != exclude:
        ifaces.append(default_dev)

    net_dir = Path("/sys/class/net")
    if net_dir.exists():
        for entry in sorted(net_dir.iterdir()):
            n = entry.name
            if n in ("lo", exclude) or n.startswith(("vmnet", "docker", "br-", "veth", "virbr")):
                continue
            if n not in ifaces:
                ifaces.append(n)
    return ifaces


def detect_default_upstream() -> str:
    if not shutil.which("ip"):
        return ""
    out = _run(["ip", "route", "show", "default"]).stdout
    m = re.search(r"\bdev\s+(\S+)", out)
    return m.group(1) if m else ""


def check_8852cu_ap_params() -> tuple[bool, str]:
    """Return (ok, message) for 8852cu module HE/VHT AP parameters."""
    he_path = Path("/sys/module/8852cu/parameters/rtw_he_enable")
    vht_path = Path("/sys/module/8852cu/parameters/rtw_vht_enable")
    if not he_path.exists():
        return True, ""
    he = he_path.read_text().strip()
    vht = vht_path.read_text().strip() if vht_path.exists() else ""
    if he != "2" or vht != "2":
        return False, f"8852cu loaded with rtw_he_enable={he}, rtw_vht_enable={vht} (AP Wi-Fi 6 needs =2)"
    return True, "8852cu Wi-Fi 6 AP params active (rtw_he_enable=2, rtw_vht_enable=2)"


def wifi_qr_payload(ssid: str, password: str, security: str) -> str:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace(":", "\\:")

    sec = "SAE" if security == "wpa3" else "WPA"
    return f"WIFI:T:{sec};S:{esc(ssid)};P:{esc(password)};;"


def read_status() -> dict[str, Any]:
    status: dict[str, Any] = {
        "active": False,
        "backend": "",
        "iface": "",
        "ssid": "",
        "band": "",
        "channel": "",
        "upstream": "",
        "ap_ip": "",
        "started_at": 0,
        "clients": [],
    }
    state_file = STATE_DIR / "state.json"
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text())
            status.update(data)
            # Verify daemon is still alive
            if data.get("backend") == "hostapd":
                pid_file = STATE_DIR / "hostapd.pid"
                if pid_file.exists():
                    pid = int(pid_file.read_text().strip())
                    if Path(f"/proc/{pid}").exists():
                        status["active"] = True
            elif data.get("backend") == "nmcli":
                out = _run(["nmcli", "-t", "-f", "NAME", "con", "show", "--active"]).stdout
                if NM_CON_NAME in out.splitlines():
                    status["active"] = True
        except Exception:
            pass

    if status["active"] and status["iface"]:
        status["clients"] = get_connected_clients(status["iface"])

    return status


def get_connected_clients(iface: str) -> list[dict[str, str]]:
    clients: list[dict[str, str]] = []
    if not shutil.which("iw"):
        return clients

    # Load DHCP lease map (mac -> ip, hostname)
    leases: dict[str, tuple[str, str]] = {}
    lease_file = STATE_DIR / "dnsmasq.leases"
    if lease_file.exists():
        for line in lease_file.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 4:
                leases[parts[1].lower()] = (parts[2], parts[3])

    out = _run(["iw", "dev", iface, "station", "dump"]).stdout
    cur: dict[str, str] | None = None
    for line in out.splitlines():
        if line.startswith("Station "):
            if cur:
                clients.append(cur)
            mac = line.split()[1].lower()
            ip, host = leases.get(mac, ("-", "-"))
            cur = {
                "mac": mac,
                "ip": ip,
                "hostname": host if host != "*" else "-",
                "signal": "-",
                "tx_bitrate": "-",
                "rx_bitrate": "-",
            }
        elif cur:
            s = line.strip()
            if s.startswith("signal:"):
                cur["signal"] = s.split(":", 1)[1].strip()
            elif s.startswith("tx bitrate:"):
                cur["tx_bitrate"] = s.split(":", 1)[1].strip().split()[0] + " Mbps"
            elif s.startswith("rx bitrate:"):
                cur["rx_bitrate"] = s.split(":", 1)[1].strip().split()[0] + " Mbps"
    if cur:
        clients.append(cur)
    return clients


def _center_freq_idx(channel: int) -> int:
    mapping = {
        36: 42, 40: 42, 44: 42, 48: 42,
        149: 155, 153: 155, 157: 155, 161: 155,
    }
    return mapping.get(channel, 42)


def start_ap_root(cfg: APConfig) -> tuple[bool, str]:
    """Start AP (must be run as root)."""
    if os.geteuid() != 0:
        return False, "Root privileges required."
    if not cfg.iface:
        return False, "No wireless interface selected."
    if not (8 <= len(cfg.password) <= 63):
        return False, "Password must be 8-63 characters."

    stop_ap_root()
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    if cfg.backend == "nmcli":
        if not shutil.which("nmcli"):
            return False, "nmcli not found."
        _run(["nmcli", "con", "delete", NM_CON_NAME])
        _run(["nmcli", "dev", "disconnect", cfg.iface])
        nm_band = "bg" if cfg.band == "2g" else "a"
        proc = _run([
            "nmcli", "dev", "wifi", "hotspot",
            "ifname", cfg.iface,
            "con-name", NM_CON_NAME,
            "ssid", cfg.ssid,
            "band", nm_band,
            "channel", str(cfg.channel),
            "password", cfg.password,
        ])
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout or "nmcli hotspot failed").strip()
        (STATE_DIR / "state.json").write_text(json.dumps({
            "backend": "nmcli",
            "iface": cfg.iface,
            "ssid": cfg.ssid,
            "band": cfg.band,
            "channel": cfg.channel,
            "upstream": cfg.upstream if cfg.share_internet else "",
            "ap_ip": "10.42.0.1/24",
            "started_at": int(time.time()),
        }, indent=2))
        return True, f"Hotspot '{cfg.ssid}' started on {cfg.iface} via NetworkManager."

    # hostapd + dnsmasq backend
    if not shutil.which("hostapd") or not shutil.which("dnsmasq"):
        return False, "hostapd and dnsmasq must be installed (or switch backend to NetworkManager)."

    if shutil.which("nmcli"):
        _run(["nmcli", "dev", "disconnect", cfg.iface])
        _run(["nmcli", "dev", "set", cfg.iface, "managed", "no"])

    _run(["ip", "link", "set", cfg.iface, "down"])
    _run(["ip", "addr", "flush", "dev", cfg.iface])
    _run(["ip", "addr", "add", f"{AP_IP}/24", "dev", cfg.iface])
    _run(["ip", "link", "set", cfg.iface, "up"])

    hw_mode = "g" if cfg.band == "2g" else "a"
    lines = [
        f"interface={cfg.iface}",
        "driver=nl80211",
        f"country_code={cfg.country.upper()}",
        "ieee80211d=1",
        f"ssid={cfg.ssid}",
        f"hw_mode={hw_mode}",
        f"channel={cfg.channel}",
        "wmm_enabled=1",
        "ieee80211n=1",
        "ht_capab=[LDPC][HT40+][SHORT-GI-20][SHORT-GI-40][TX-STBC][RX-STBC1][MAX-AMSDU-7935]",
    ]
    if cfg.wifi6:
        lines.append("ieee80211ax=1")
        lines.append("he_bss_color=37")

    if hw_mode == "a":
        seg0 = _center_freq_idx(cfg.channel)
        chwidth = 1 if cfg.width == "80" else 0
        lines.extend([
            "ieee80211ac=1",
            f"vht_oper_chwidth={chwidth}",
            f"vht_oper_centr_freq_seg0_idx={seg0}",
            "vht_capab=[MAX-MPDU-7991][RXLDPC][SHORT-GI-80][TX-STBC-2BY1][RX-STBC-1][SU-BEAMFORMEE][MU-BEAMFORMEE][MAX-A-MPDU-LEN-EXP7]",
        ])
        if cfg.wifi6:
            lines.extend([
                f"he_oper_chwidth={chwidth}",
                f"he_oper_centr_freq_seg0_idx={seg0}",
            ])

    if cfg.security == "wpa3":
        lines.extend([
            "auth_algs=1",
            "wpa=2",
            "wpa_key_mgmt=SAE",
            "ieee80211w=2",
            "rsn_pairwise=CCMP",
            f"wpa_passphrase={cfg.password}",
        ])
    elif cfg.security == "wpa2-wpa3":
        lines.extend([
            "auth_algs=1",
            "wpa=2",
            "wpa_key_mgmt=WPA-PSK SAE",
            "ieee80211w=1",
            "rsn_pairwise=CCMP",
            f"wpa_passphrase={cfg.password}",
        ])
    else:
        lines.extend([
            "auth_algs=1",
            "wpa=2",
            "wpa_key_mgmt=WPA-PSK",
            "rsn_pairwise=CCMP",
            f"wpa_passphrase={cfg.password}",
        ])

    hostapd_conf = STATE_DIR / "hostapd.conf"
    hostapd_conf.write_text("\n".join(lines) + "\n")
    hostapd_conf.chmod(0o600)

    dnsmasq_conf = STATE_DIR / "dnsmasq.conf"
    dnsmasq_conf.write_text(
        f"interface={cfg.iface}\n"
        "bind-interfaces\n"
        f"dhcp-range={AP_SUBNET}.10,{AP_SUBNET}.200,255.255.255.0,12h\n"
        f"dhcp-option=option:router,{AP_IP}\n"
        "dhcp-option=option:dns-server,1.1.1.1,8.8.8.8\n"
        f"dhcp-leasefile={STATE_DIR}/dnsmasq.leases\n"
        f"pid-file={STATE_DIR}/dnsmasq.pid\n"
    )

    if cfg.share_internet and cfg.upstream:
        _run(["sysctl", "-w", "net.ipv4.ip_forward=1"])
        if shutil.which("nft"):
            nft_rules = (
                "table inet aircast_ap {\n"
                "  chain forward {\n"
                "    type filter hook forward priority 0; policy accept;\n"
                f'    iifname "{cfg.iface}" oifname "{cfg.upstream}" accept\n'
                f'    iifname "{cfg.upstream}" oifname "{cfg.iface}" ct state related,established accept\n'
                "  }\n"
                "  chain postrouting {\n"
                "    type nat hook postrouting priority 100; policy accept;\n"
                f'    oifname "{cfg.upstream}" masquerade\n'
                "  }\n"
                "}\n"
            )
            subprocess.run(["nft", "-f", "-"], input=nft_rules, text=True, capture_output=True)
        elif shutil.which("iptables"):
            _run(["iptables", "-t", "nat", "-A", "POSTROUTING", "-o", cfg.upstream, "-j", "MASQUERADE"])
            _run(["iptables", "-A", "FORWARD", "-i", cfg.iface, "-o", cfg.upstream, "-j", "ACCEPT"])
            _run(["iptables", "-A", "FORWARD", "-i", cfg.upstream, "-o", cfg.iface, "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"])

    dns_proc = _run(["dnsmasq", f"--conf-file={dnsmasq_conf}"])
    if dns_proc.returncode != 0:
        stop_ap_root()
        return False, f"dnsmasq failed: {(dns_proc.stderr or dns_proc.stdout).strip()}"

    hap_proc = _run(["hostapd", "-B", "-P", str(STATE_DIR / "hostapd.pid"), str(hostapd_conf)])
    if hap_proc.returncode != 0:
        stop_ap_root()
        return False, f"hostapd failed: {(hap_proc.stderr or hap_proc.stdout).strip()}"

    (STATE_DIR / "state.json").write_text(json.dumps({
        "backend": "hostapd",
        "iface": cfg.iface,
        "ssid": cfg.ssid,
        "band": cfg.band,
        "channel": cfg.channel,
        "upstream": cfg.upstream if cfg.share_internet else "",
        "ap_ip": f"{AP_IP}/24",
        "started_at": int(time.time()),
    }, indent=2))
    return True, f"Wi-Fi 6 AP '{cfg.ssid}' started on {cfg.iface} ({AP_IP}/24)."


def stop_ap_root() -> tuple[bool, str]:
    """Stop any running AP and restore interface to managed mode (must be root)."""
    if os.geteuid() != 0:
        return False, "Root privileges required."

    iface = ""
    upstream = ""
    backend = ""
    state_file = STATE_DIR / "state.json"
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text())
            iface = data.get("iface", "")
            upstream = data.get("upstream", "")
            backend = data.get("backend", "")
        except Exception:
            pass

    if shutil.which("nmcli"):
        if backend == "nmcli" or NM_CON_NAME in _run(["nmcli", "-t", "-f", "NAME", "con", "show", "--active"]).stdout.splitlines():
            _run(["nmcli", "con", "down", NM_CON_NAME])
            _run(["nmcli", "con", "delete", NM_CON_NAME])

    for pid_name in ("hostapd.pid", "dnsmasq.pid"):
        pf = STATE_DIR / pid_name
        if pf.exists():
            try:
                os.kill(int(pf.read_text().strip()), 15)
            except Exception:
                pass

    if shutil.which("nft"):
        _run(["nft", "delete", "table", "inet", "aircast_ap"])
    if iface and upstream and shutil.which("iptables"):
        _run(["iptables", "-t", "nat", "-D", "POSTROUTING", "-o", upstream, "-j", "MASQUERADE"])
        _run(["iptables", "-D", "FORWARD", "-i", iface, "-o", upstream, "-j", "ACCEPT"])
        _run(["iptables", "-D", "FORWARD", "-i", upstream, "-o", iface, "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"])

    if iface:
        _run(["ip", "addr", "flush", "dev", iface])
        _run(["ip", "link", "set", iface, "down"])
        if shutil.which("iw"):
            _run(["iw", "dev", iface, "set", "type", "managed"])
        _run(["ip", "link", "set", iface, "up"])
        if shutil.which("nmcli"):
            _run(["nmcli", "dev", "set", iface, "managed", "yes"])

    shutil.rmtree(STATE_DIR, ignore_errors=True)
    return True, "AP stopped and interface restored."


def apply_8852cu_ap_params_root() -> tuple[bool, str]:
    """Enable rtw_he_enable=2 rtw_vht_enable=2 in /etc/modprobe.d/8852cu.conf and reload."""
    if os.geteuid() != 0:
        return False, "Root privileges required."
    modopt = Path("/etc/modprobe.d/8852cu.conf")
    if modopt.exists():
        text = modopt.read_text()
        if re.search(r"^options 8852cu\b", text, re.MULTILINE):
            def patch_line(m: re.Match[str]) -> str:
                line = m.group(0)
                for key in ("rtw_he_enable", "rtw_vht_enable"):
                    if f"{key}=" in line:
                        line = re.sub(rf"{key}=\d+", f"{key}=2", line)
                    else:
                        line += f" {key}=2"
                return line

            text = re.sub(r"^options 8852cu.*$", patch_line, text, count=1, flags=re.MULTILINE)
        else:
            text += "\noptions 8852cu rtw_switch_usb_mode=1 rtw_he_enable=2 rtw_vht_enable=2\n"
        modopt.write_text(text)
    else:
        modopt.write_text("options 8852cu rtw_switch_usb_mode=1 rtw_he_enable=2 rtw_vht_enable=2\n")

    _run(["modprobe", "-r", "8852cu"])
    p = _run(["modprobe", "8852cu"])
    if p.returncode != 0:
        return False, (p.stderr or p.stdout or "Failed to reload 8852cu").strip()
    return True, "Enabled Wi-Fi 6 AP parameters (rtw_he_enable=2, rtw_vht_enable=2) and reloaded 8852cu."
