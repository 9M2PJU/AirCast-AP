#!/usr/bin/env python3
"""AirCast-AP - CLI & privileged helper entry point."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .backend import (
    APConfig,
    apply_8852cu_ap_params_root,
    check_8852cu_ap_params,
    list_upstream_interfaces,
    list_wifi_interfaces,
    read_status,
    start_ap_root,
    stop_ap_root,
    wifi_qr_payload,
)


def elevate_command(args: list[str]) -> tuple[bool, str]:
    """Run privileged CLI subcommand via pkexec (GUI) or sudo (TTY)."""
    pkg_root = str(Path(__file__).resolve().parent.parent)
    helper = ["env", f"PYTHONPATH={pkg_root}", sys.executable, "-m", "aircast_ap.cli", *args]
    if os.geteuid() == 0:
        cmd = [sys.executable, "-m", "aircast_ap.cli", *args]
    elif shutil.which("pkexec") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        cmd = ["pkexec", *helper]
    elif shutil.which("sudo"):
        cmd = ["sudo", *helper]
    else:
        return False, "Neither pkexec nor sudo found."

    proc = subprocess.run(cmd, text=True, capture_output=True)
    msg = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode == 0, msg


def cmd_start(args: argparse.Namespace) -> int:
    if args.config_json:
        data = json.loads(Path(args.config_json).read_text())
        cfg = APConfig(**{k: v for k, v in data.items() if k in APConfig.__dataclass_fields__})
    else:
        cfg = APConfig.load()
        if args.iface:
            cfg.iface = args.iface
        if args.ssid:
            cfg.ssid = args.ssid
        if args.password:
            cfg.password = args.password
        if args.band:
            cfg.band = args.band
            cfg.channel = 36 if args.band == "5g-low" else (149 if args.band == "5g-high" else 6)
        if args.channel:
            cfg.channel = args.channel
        if args.country:
            cfg.country = args.country
        if args.security:
            cfg.security = args.security
        if args.backend:
            cfg.backend = args.backend
        if args.upstream is not None:
            cfg.upstream = args.upstream
            cfg.share_internet = bool(args.upstream)
        if not cfg.iface:
            ifaces = list_wifi_interfaces()
            if ifaces:
                cfg.iface = ifaces[0].name

    ok, msg = start_ap_root(cfg)
    print(msg)
    if ok and args.qr and shutil.which("qrencode"):
        subprocess.run(["qrencode", "-t", "ANSIUTF8", wifi_qr_payload(cfg.ssid, cfg.password, cfg.security)])
    return 0 if ok else 1


def cmd_stop(_args: argparse.Namespace) -> int:
    ok, msg = stop_ap_root()
    print(msg)
    return 0 if ok else 1


def cmd_status(args: argparse.Namespace) -> int:
    st = read_status()
    if args.json:
        print(json.dumps(st, indent=2))
        return 0

    state_str = "ACTIVE" if st["active"] else "INACTIVE"
    print(f"AirCast-AP v{__version__} - {state_str}")
    if st["active"]:
        print(f"  Interface : {st['iface']} ({st['ap_ip']})")
        print(f"  SSID      : {st['ssid']} (band: {st['band']}, ch: {st['channel']})")
        print(f"  Backend   : {st['backend']}")
        print(f"  Upstream  : {st['upstream'] or 'local-only'}")
        print(f"  Clients   : {len(st['clients'])}")
        for c in st["clients"]:
            print(f"    - {c['mac']}  {c['ip']}  ({c['hostname']})  sig={c['signal']}  tx={c['tx_bitrate']}")
    return 0


def cmd_devices(_args: argparse.Namespace) -> int:
    ifaces = list_wifi_interfaces()
    if not ifaces:
        print("No wireless interfaces found.")
        return 0
    for w in ifaces:
        print(f"{w.name:10s}  driver={w.driver or '?':14s}  mac={w.mac}  ap={w.ap_supported}  wifi6_ap={w.wifi6_ap}")
    ok_8852, msg_8852 = check_8852cu_ap_params()
    if msg_8852:
        print(f"\n[{'OK' if ok_8852 else 'WARN'}] {msg_8852}")
    return 0


def cmd_tune_8852cu(_args: argparse.Namespace) -> int:
    ok, msg = apply_8852cu_ap_params_root()
    print(msg)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aircast-ap", description="AirCast-AP - Linux Wi-Fi 6 Access Point Manager")
    parser.add_argument("--version", action="version", version=f"AirCast-AP {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    p_gui = sub.add_parser("gui", help="Launch GTK4 + Libadwaita desktop app (default)")
    p_gui.set_defaults(cmd="gui")

    p_start = sub.add_parser("start", help="Start Access Point")
    p_start.add_argument("--config-json", help="Path to JSON config file")
    p_start.add_argument("-i", "--iface", help="AP Wi-Fi interface (e.g. wlan1)")
    p_start.add_argument("-s", "--ssid", help="Network SSID")
    p_start.add_argument("-p", "--password", help="WPA2/WPA3 password (8-63 chars)")
    p_start.add_argument("-b", "--band", choices=["5g-low", "5g-high", "2g"], help="Band preset")
    p_start.add_argument("-c", "--channel", type=int, help="Wi-Fi channel")
    p_start.add_argument("--country", help="2-letter ISO country code")
    p_start.add_argument("--security", choices=["wpa2", "wpa2-wpa3", "wpa3"])
    p_start.add_argument("--backend", choices=["hostapd", "nmcli"])
    p_start.add_argument("-u", "--upstream", help="Upstream NAT interface (empty = local-only)")
    p_start.add_argument("--qr", action="store_true", help="Print Wi-Fi QR code in terminal")

    sub.add_parser("stop", help="Stop Access Point and restore client mode")

    p_stat = sub.add_parser("status", help="Show AP status and connected clients")
    p_stat.add_argument("--json", action="store_true", help="Output JSON")

    sub.add_parser("devices", help="List Wi-Fi interfaces and AP capabilities")
    sub.add_parser("tune-8852cu", help="Enable rtw_he_enable=2 & rtw_vht_enable=2 for RTL8852CU AP mode")

    args = parser.parse_args(argv)
    if args.cmd in (None, "gui"):
        from .gui import launch_gui
        return launch_gui()
    if args.cmd == "start":
        return cmd_start(args)
    if args.cmd == "stop":
        return cmd_stop(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "devices":
        return cmd_devices(args)
    if args.cmd == "tune-8852cu":
        return cmd_tune_8852cu(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
