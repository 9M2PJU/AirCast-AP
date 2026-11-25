#!/usr/bin/env python3
"""AirCast-AP — Modern GTK4 + Libadwaita Native Wayland GUI."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__
from .backend import (
    APConfig,
    check_8852cu_ap_params,
    list_upstream_interfaces,
    list_wifi_interfaces,
    read_status,
    wifi_qr_payload,
)
from .cli import elevate_command

BAND_OPTIONS = [
    ("5g-low", "5 GHz Wi-Fi 6 • Channel 36 (80 MHz)", 36),
    ("5g-high", "5 GHz Wi-Fi 6 • Channel 149 (80 MHz)", 149),
    ("2g", "2.4 GHz Wi-Fi 6 • Channel 6 (20 MHz)", 6),
]
SEC_OPTIONS = [
    ("wpa2", "WPA2-PSK (AES/CCMP — Best Compatibility)"),
    ("wpa2-wpa3", "WPA2 / WPA3 Mixed (Transition)"),
    ("wpa3", "WPA3-SAE Only"),
]
BACKEND_OPTIONS = [
    ("hostapd", "hostapd + dnsmasq (Full Wi-Fi 6 / 80 MHz)"),
    ("nmcli", "NetworkManager Hotspot (Zero Extra Config)"),
]


def _make_qr_texture(payload: str) -> Gdk.Texture | None:
    try:
        import qrcode  # type: ignore

        qr = qrcode.QRCode(border=2, box_size=6)
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#11111b", back_color="#ffffff")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        gbytes = GLib.Bytes.new(buf.getvalue())
        return Gdk.Texture.new_from_bytes(gbytes)
    except Exception:
        return None


class AirCastWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="AirCast-AP")
        self.set_default_size(640, 760)
        self.cfg = APConfig.load()
        self.wifi_ifaces = list_wifi_interfaces()
        self.upstreams = list_upstream_interfaces(self.cfg.iface)
        self._busy = False

        # Toast overlay + ToolbarView
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        # Header refresh & about buttons
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh interfaces & status")
        refresh_btn.connect("clicked", lambda *_: self.refresh_all())
        header.pack_start(refresh_btn)

        about_btn = Gtk.Button(icon_name="help-about-symbolic", tooltip_text="About AirCast-AP")
        about_btn.connect("clicked", self._show_about)
        header.pack_end(about_btn)

        # Scrollable clamped content
        scroll = Gtk.ScrolledWindow(vexpand=True)
        clamp = Adw.Clamp(maximum_size=600, margin_top=16, margin_bottom=24, margin_start=16, margin_end=16)
        scroll.set_child(clamp)
        toolbar_view.set_content(scroll)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp.set_child(box)

        # --- Hero Status Banner ---
        self.status_card = Adw.PreferencesGroup()
        box.append(self.status_card)

        self.status_row = Adw.ActionRow(title="Access Point Inactive", subtitle="Configure below and press Start Access Point")
        self.status_icon = Gtk.Image.new_from_icon_name("network-wireless-offline-symbolic")
        self.status_icon.set_pixel_size(32)
        self.status_row.add_prefix(self.status_icon)

        self.toggle_btn = Gtk.Button(label="Start AP")
        self.toggle_btn.add_css_class("suggested-action")
        self.toggle_btn.add_css_class("pill")
        self.toggle_btn.set_valign(Gtk.Align.CENTER)
        self.toggle_btn.connect("clicked", self._on_toggle_ap)
        self.status_row.add_suffix(self.toggle_btn)
        self.status_card.add(self.status_row)

        # Optional 8852cu Wi-Fi 6 AP hint banner
        self.tune_banner = Adw.Banner(
            title="RTL8852CU detected — enable Wi-Fi 6 AP params (rtw_he_enable=2, rtw_vht_enable=2)",
            button_label="Enable & Reload",
        )
        self.tune_banner.connect("button-clicked", self._on_tune_8852cu)
        box.append(self.tune_banner)

        # --- Network Settings Group ---
        net_group = Adw.PreferencesGroup(title="Access Point Configuration", description="Works with Realtek RTL8852CU, MediaTek, Intel, and any nl80211 AP-capable adapter")
        box.append(net_group)

        self.iface_row = Adw.ComboRow(title="Wi-Fi Adapter")
        net_group.add(self.iface_row)

        self.ssid_row = Adw.EntryRow(title="Network Name (SSID)")
        self.ssid_row.set_text(self.cfg.ssid)
        net_group.add(self.ssid_row)

        self.pass_row = Adw.PasswordEntryRow(title="Passphrase (8–63 characters)")
        self.pass_row.set_text(self.cfg.password)
        net_group.add(self.pass_row)

        self.band_row = Adw.ComboRow(title="Band & Channel")
        self.band_row.set_model(Gtk.StringList.new([b[1] for b in BAND_OPTIONS]))
        for idx, (k, _, _) in enumerate(BAND_OPTIONS):
            if k == self.cfg.band:
                self.band_row.set_selected(idx)
        net_group.add(self.band_row)

        self.sec_row = Adw.ComboRow(title="Security")
        self.sec_row.set_model(Gtk.StringList.new([s[1] for s in SEC_OPTIONS]))
        for idx, (k, _) in enumerate(SEC_OPTIONS):
            if k == self.cfg.security:
                self.sec_row.set_selected(idx)
        net_group.add(self.sec_row)

        self.country_row = Adw.EntryRow(title="Country Code (ISO 2-letter)")
        self.country_row.set_text(self.cfg.country)
        net_group.add(self.country_row)

        # --- Internet Sharing & Backend Group ---
        adv_group = Adw.PreferencesGroup(title="Internet Sharing & Engine")
        box.append(adv_group)

        self.backend_row = Adw.ComboRow(title="AP Backend")
        self.backend_row.set_model(Gtk.StringList.new([b[1] for b in BACKEND_OPTIONS]))
        for idx, (k, _) in enumerate(BACKEND_OPTIONS):
            if k == self.cfg.backend:
                self.backend_row.set_selected(idx)
        adv_group.add(self.backend_row)

        self.share_row = Adw.SwitchRow(title="Share Internet (NAT)", subtitle="Route client traffic via upstream interface")
        self.share_row.set_active(self.cfg.share_internet)
        adv_group.add(self.share_row)

        self.upstream_row = Adw.ComboRow(title="Upstream Interface")
        adv_group.add(self.upstream_row)

        # --- QR Code Share Card ---
        self.qr_group = Adw.PreferencesGroup(title="Quick Phone Connect (Wi-Fi QR)")
        box.append(self.qr_group)
        qr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        self.qr_picture = Gtk.Picture()
        self.qr_picture.set_size_request(148, 148)
        self.qr_picture.set_can_shrink(True)
        qr_box.append(self.qr_picture)

        qr_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER)
        self.qr_label = Gtk.Label(xalign=0, wrap=True)
        qr_info.append(self.qr_label)
        qr_box.append(qr_info)
        self.qr_group.add(qr_box)

        # --- Connected Clients Group ---
        self.clients_group = Adw.PreferencesGroup(title="Connected Clients (0)")
        box.append(self.clients_group)
        self.client_rows: list[Gtk.Widget] = []

        # Live QR updates
        self.ssid_row.connect("changed", lambda *_: self._update_qr())
        self.pass_row.connect("changed", lambda *_: self._update_qr())
        self.sec_row.connect("notify::selected", lambda *_: self._update_qr())

        self.refresh_all()
        GLib.timeout_add_seconds(4, self._poll_status)

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def _populate_combos(self) -> None:
        self.wifi_ifaces = list_wifi_interfaces()
        labels = [w.label for w in self.wifi_ifaces] or ["No Wi-Fi adapter detected"]
        self.iface_row.set_model(Gtk.StringList.new(labels))
        for idx, w in enumerate(self.wifi_ifaces):
            if w.name == self.cfg.iface:
                self.iface_row.set_selected(idx)
                break

        cur_iface = self.wifi_ifaces[self.iface_row.get_selected()].name if self.wifi_ifaces else ""
        self.upstreams = list_upstream_interfaces(exclude=cur_iface)
        up_labels = self.upstreams or ["None"]
        self.upstream_row.set_model(Gtk.StringList.new(up_labels))
        for idx, u in enumerate(self.upstreams):
            if u == self.cfg.upstream:
                self.upstream_row.set_selected(idx)
                break

    def _update_qr(self) -> None:
        ssid = self.ssid_row.get_text().strip() or "AirCast-AX"
        pw = self.pass_row.get_text()
        sec = SEC_OPTIONS[self.sec_row.get_selected()][0]
        tex = _make_qr_texture(wifi_qr_payload(ssid, pw, sec))
        if tex:
            self.qr_picture.set_paintable(tex)
            self.qr_label.set_markup(
                f"<b>Scan with your phone camera</b>\nSSID: <tt>{GLib.markup_escape_text(ssid)}</tt>\nSecurity: {sec.upper()}"
            )
            self.qr_group.set_visible(True)
        else:
            self.qr_group.set_visible(False)

    def _gather_config(self) -> APConfig:
        iface = self.wifi_ifaces[self.iface_row.get_selected()].name if self.wifi_ifaces else ""
        band_key, _, chan = BAND_OPTIONS[self.band_row.get_selected()]
        sec_key = SEC_OPTIONS[self.sec_row.get_selected()][0]
        backend_key = BACKEND_OPTIONS[self.backend_row.get_selected()][0]
        upstream = self.upstreams[self.upstream_row.get_selected()] if self.upstreams else ""
        return APConfig(
            iface=iface,
            ssid=self.ssid_row.get_text().strip() or "AirCast-AX",
            password=self.pass_row.get_text(),
            band=band_key,
            channel=chan,
            width="80" if band_key != "2g" else "20",
            country=(self.country_row.get_text().strip() or "MY").upper()[:2],
            security=sec_key,
            backend=backend_key,
            share_internet=self.share_row.get_active(),
            upstream=upstream,
            wifi6=True,
        )

    def refresh_all(self) -> None:
        self._populate_combos()
        ok_8852, _ = check_8852cu_ap_params()
        self.tune_banner.set_revealed(not ok_8852)
        self._update_qr()
        self._poll_status()

    def _poll_status(self) -> bool:
        st = read_status()
        if st["active"]:
            self.status_row.set_title(f"LIVE • {st['ssid']}")
            self.status_row.set_subtitle(
                f"{st['iface']} ({st['ap_ip']}) • Ch {st['channel']} • {st['backend']} • Upstream: {st['upstream'] or 'local'}"
            )
            self.status_icon.set_from_icon_name("network-wireless-hotspot-symbolic")
            self.toggle_btn.set_label("Stop AP")
            self.toggle_btn.remove_css_class("suggested-action")
            self.toggle_btn.add_css_class("destructive-action")
        else:
            self.status_row.set_title("Access Point Inactive")
            self.status_row.set_subtitle("Ready — configure your hotspot and press Start AP")
            self.status_icon.set_from_icon_name("network-wireless-offline-symbolic")
            self.toggle_btn.set_label("Start AP")
            self.toggle_btn.remove_css_class("destructive-action")
            self.toggle_btn.add_css_class("suggested-action")

        # Refresh client list
        for r in self.client_rows:
            self.clients_group.remove(r)
        self.client_rows.clear()

        clients = st.get("clients", [])
        self.clients_group.set_title(f"Connected Clients ({len(clients)})")
        if not clients:
            empty = Adw.ActionRow(title="No clients connected", subtitle="Devices joining your hotspot will appear here")
            self.clients_group.add(empty)
            self.client_rows.append(empty)
        else:
            for c in clients:
                row = Adw.ActionRow(
                    title=f"{c['hostname']} ({c['ip']})",
                    subtitle=f"MAC {c['mac']} • Signal {c['signal']} • TX {c['tx_bitrate']}",
                )
                row.add_prefix(Gtk.Image.new_from_icon_name("computer-symbolic"))
                self.clients_group.add(row)
                self.client_rows.append(row)
        return True

    def _run_async(self, args: list[str], cleanup_file: Path | None = None) -> None:
        if self._busy:
            return
        self._busy = True
        self.toggle_btn.set_sensitive(False)

        def worker() -> None:
            ok, msg = elevate_command(args)
            if cleanup_file:
                cleanup_file.unlink(missing_ok=True)

            def finish() -> bool:
                self._busy = False
                self.toggle_btn.set_sensitive(True)
                self._toast(msg or ("Done" if ok else "Action failed"))
                self.refresh_all()
                return False

            GLib.idle_add(finish)

        threading.Thread(target=worker, daemon=True).start()

    def _on_toggle_ap(self, *_args: object) -> None:
        st = read_status()
        if st["active"]:
            self._run_async(["stop"])
            return

        cfg = self._gather_config()
        if len(cfg.password) < 8 or len(cfg.password) > 63:
            self._toast("Password must be 8–63 characters")
            return
        cfg.save()

        tmp = Path(tempfile.mkstemp(prefix="aircast-", suffix=".json")[1])
        tmp.write_text(json.dumps(cfg.to_dict()))
        tmp.chmod(0o644)
        self._run_async(["start", "--config-json", str(tmp)], cleanup_file=tmp)

    def _on_tune_8852cu(self, *_args: object) -> None:
        self._run_async(["tune-8852cu"])

    def _show_about(self, *_args: object) -> None:
        dlg = Adw.AboutDialog(
            application_name="AirCast-AP",
            application_icon="network-wireless-hotspot-symbolic",
            developer_name="9M2PJU",
            version=__version__,
            website="https://github.com/9M2PJU/AirCast-AP",
            issue_url="https://github.com/9M2PJU/AirCast-AP/issues",
            license_type=Gtk.License.GPL_3_0,
            comments="Modern GTK4 + Libadwaita Wi-Fi 6 Access Point & Hotspot Manager for Linux.\nBuilt as a companion to rtl8852cu-9M2PJU-dkms. 73 de 9M2PJU!",
        )
        dlg.present(self)


class AirCastApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="my.hamradio.AirCastAP", flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self) -> None:
        win = self.props.active_window
        if not win:
            win = AirCastWindow(self)
        win.present()


def launch_gui() -> int:
    app = AirCastApp()
    return app.run(sys.argv[:1])
