"""Scan a QR code, phone becomes the microphone. Like pairing a headset.

THE ONE THING THAT BREAKS EVERY PHONE-MIC SETUP
-----------------------------------------------
Browsers refuse `getUserMedia` outside a **secure context**. `localhost` is
exempt; `http://192.168.1.117:8765` is not. So the obvious approach -- print
a QR of the LAN address -- produces a page that loads perfectly and then
fails to get the microphone, with an error most people read as "ZENO is
broken".

That single fact determines this whole module. It does not hand out a URL
that cannot work. It finds a transport that gives HTTPS, and if none exists
it says so instead of producing a QR that leads to a dead end.

THE THREE ROUTES, BEST FIRST
----------------------------
1. **Tailscale** — already running here. `tailscale cert` issues a REAL
   certificate for the machine's MagicDNS name, so the phone sees no warning
   at all. The phone needs Tailscale too, and then it works on any network,
   not just this one. This is the closest thing to plugging in a headset.
2. **LAN with a self-signed certificate** — works on the same Wi-Fi with a
   one-time "this connection is not private → proceed". Ugly once, fine
   forever after. No account, no internet.
3. **Cloudflare Tunnel** — the existing route. Public, needs an account, and
   is more than is warranted for "use my phone as a mic".

THE CERTIFICATE DETAIL THAT MATTERS
-----------------------------------
A self-signed cert for an IP address must carry that IP in
`subjectAltName`. Browsers stopped reading Common Name years ago, so a cert
without a SAN is rejected outright and the fallback fails for a reason
nobody can see. The generator below always sets it.
"""

from __future__ import annotations

import datetime
import ipaddress
import json
import os
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent.capabilities import inventory

TAILSCALE = "tailscale"
LAN_TLS = "lan_https"
TUNNEL = "cloudflare"
NONE = "none"

DEFAULT_PORT = 8765
# A separate HTTPS port so the plain-HTTP desktop server keeps working.
TLS_PORT = 8766

CERT_DAYS = 825


def _cert_dir() -> Path:
    from reyes_agent import config

    return Path(config.VAULT_PATH) / "07-System" / "mic-tls"


def lan_ip() -> str:
    """The address this machine has on the local network."""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        address = probe.getsockname()[0]
        probe.close()
        return address
    except Exception:  # noqa: BLE001
        return ""


def tailscale_name() -> tuple[str, str]:
    """(MagicDNS name, tailscale IP). Empty when Tailscale is not running."""
    binary = inventory.find_application("tailscale")
    if not binary:
        return "", ""
    try:
        result = subprocess.run([binary, "status", "--json"], capture_output=True,
                                text=True, timeout=20,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0:
            return "", ""
        data = json.loads(result.stdout or "{}")
        if str(data.get("BackendState", "")).lower() != "running":
            return "", ""
        me = data.get("Self") or {}
        name = str(me.get("DNSName", "")).rstrip(".")
        address = (data.get("TailscaleIPs") or [""])[0]
        magic = (data.get("CurrentTailnet") or {}).get("MagicDNSEnabled")
        return (name if magic else ""), address
    except Exception:  # noqa: BLE001
        return "", ""


def tailscale_cert(host: str) -> tuple[str, str]:
    """Ask Tailscale for a real certificate. (cert path, key path) or ("","")."""
    binary = inventory.find_application("tailscale")
    if not binary or not host:
        return "", ""
    directory = _cert_dir()
    directory.mkdir(parents=True, exist_ok=True)
    cert = directory / f"{host}.crt"
    key = directory / f"{host}.key"
    if cert.exists() and key.exists():
        return str(cert), str(key)
    try:
        result = subprocess.run(
            [binary, "cert", "--cert-file", str(cert), "--key-file", str(key), host],
            capture_output=True, text=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode == 0 and cert.exists() and key.exists():
            return str(cert), str(key)
    except Exception:  # noqa: BLE001
        pass
    return "", ""


def self_signed(address: str) -> tuple[str, str]:
    """A certificate for a bare IP, with the SAN browsers actually read."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except Exception:  # noqa: BLE001
        return "", ""

    directory = _cert_dir()
    directory.mkdir(parents=True, exist_ok=True)
    cert_path = directory / f"lan-{address.replace('.', '-')}.crt"
    key_path = directory / f"lan-{address.replace('.', '-')}.key"
    if cert_path.exists() and key_path.exists():
        return str(cert_path), str(key_path)

    try:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, address),
                          x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ZENO")])
        now = datetime.datetime.now(datetime.timezone.utc)

        # The SAN is not optional. Without it every modern browser rejects
        # the certificate outright, and the fallback fails invisibly.
        alt = [x509.IPAddress(ipaddress.ip_address(address)),
               x509.DNSName("localhost"),
               x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]

        certificate = (x509.CertificateBuilder()
                       .subject_name(name).issuer_name(name)
                       .public_key(key.public_key())
                       .serial_number(x509.random_serial_number())
                       .not_valid_before(now - datetime.timedelta(days=1))
                       .not_valid_after(now + datetime.timedelta(days=CERT_DAYS))
                       .add_extension(x509.SubjectAlternativeName(alt), critical=False)
                       .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                                      critical=True)
                       .sign(key, hashes.SHA256()))

        cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()))
        try:                                   # keep the key to this account
            os.chmod(key_path, 0o600)
        except OSError:
            pass
        return str(cert_path), str(key_path)
    except Exception:  # noqa: BLE001
        return "", ""


@dataclass
class Link:
    transport: str = NONE
    url: str = ""
    host: str = ""
    port: int = TLS_PORT
    cert: str = ""
    key: str = ""
    trusted: bool = False
    qr_png: str = ""
    steps: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.url) and self.transport != NONE

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "transport": self.transport, "url": self.url,
                "host": self.host, "port": self.port, "trusted": self.trusted,
                "cert": self.cert, "key": self.key, "steps": self.steps,
                "reason": self.reason, "qr_png": self.qr_png}

    def say(self) -> str:
        if not self.ok:
            return self.reason
        lines = [f"Scan this with your phone: {self.url}"]
        lines.extend(f"  {index}. {step}" for index, step in enumerate(self.steps, 1))
        return "\n".join(lines)


def _qr(url: str) -> str:
    try:
        import base64
        from io import BytesIO

        import qrcode

        image = qrcode.make(url)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001
        return ""


def build(*, token: str = "", port: int = TLS_PORT, prefer: str = "") -> Link:
    """Work out the best way for the phone to reach ZENO, and make a QR.

    Never returns a plain-HTTP LAN URL: the microphone cannot work there and
    handing one over would waste the owner's time at exactly the wrong moment.
    """
    query = f"?token={token}" if token else ""

    # 1. Tailscale -- a real certificate, no warning, works off this network.
    if prefer in ("", TAILSCALE):
        host, address = tailscale_name()
        if host:
            cert, key = tailscale_cert(host)
            if cert and key:
                url = f"https://{host}:{port}/mic{query}"
                return Link(TAILSCALE, url, host, port, cert, key, trusted=True,
                            qr_png=_qr(url),
                            steps=[
                                "Install Tailscale on your phone and sign in to the "
                                "same account (owntred399@gmail.com).",
                                "Scan the code. The certificate is genuine, so there "
                                "is no security warning.",
                                "Allow the microphone once when the browser asks.",
                                "It works on mobile data too, not just this Wi-Fi.",
                            ])

    # 2. LAN with a self-signed certificate -- one warning, then fine.
    if prefer in ("", LAN_TLS):
        address = lan_ip()
        if address:
            cert, key = self_signed(address)
            if cert and key:
                url = f"https://{address}:{port}/mic{query}"
                return Link(LAN_TLS, url, address, port, cert, key, trusted=False,
                            qr_png=_qr(url),
                            steps=[
                                "Keep the phone on the same Wi-Fi as this computer.",
                                "Scan the code. The phone will warn that the "
                                "connection is not private -- that is expected, the "
                                "certificate is one this computer made for itself.",
                                "Tap Advanced, then Proceed. You only do this once.",
                                "Allow the microphone when the browser asks.",
                            ])

    # 3. Cloudflare, only if the owner already set it up.
    public = os.environ.get("ZENO_PHONE_PUBLIC_HOST", "").strip()
    if public:
        url = f"https://{public}/mic{query}"
        return Link(TUNNEL, url, public, 443, trusted=True, qr_png=_qr(url),
                    steps=["Scan the code.",
                           "Allow the microphone when the browser asks."])

    return Link(NONE, reason=(
        "I cannot give you a working link yet. Phone browsers refuse microphone "
        "access over plain HTTP, so a LAN address on its own would load the page "
        "and then fail to hear anything. Tailscale is installed here — if it is "
        "signed in, I can issue a real certificate and this becomes a clean scan. "
        "Otherwise I can generate a self-signed certificate for this network, "
        "which works after a one-time browser warning."))


def status() -> dict[str, Any]:
    host, address = tailscale_name()
    return {
        "state": "ONLINE",
        "lan_ip": lan_ip(),
        "tailscale": {"magicdns": host, "ip": address, "running": bool(host)},
        "cloudflare_host": os.environ.get("ZENO_PHONE_PUBLIC_HOST", ""),
        "tls_port": TLS_PORT,
        "cert_dir": str(_cert_dir()),
        "why_https": ("Browsers refuse getUserMedia outside a secure context. A "
                      "plain-HTTP LAN link loads the page and then cannot reach the "
                      "microphone, which reads as ZENO being broken."),
        "never": "hands out a plain-HTTP URL for the microphone page",
    }
