"""AVA's toolkit: the standard security tools, offensive and defensive.

WHAT THIS IS
------------
A structured reference to the security tools a professional actually uses,
organised by kill-chain phase, each tagged offense / defense / dual. Every
tool here is publicly documented and ships in mainstream distributions (Kali,
Parrot, BlackArch) or is a well-known defensive product. Naming and describing
them is reference material, the same as any security syllabus.

Knowing a tool exists is not running it. The catalog is advisory; the
`authorization` module gates anything that touches a target.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
No tool whose purpose is indiscriminate destruction or mass harm: no DDoS
stressers, no ransomware or wiper builders, no self-propagating worm kits, no
botnet C2-for-hire. Those are on the refuse list regardless of scope, and
`engagement.py` blocks the techniques they serve. Everything present serves
assessment of a *specific authorized target* or the defense of one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OFFENSE, DEFENSE, DUAL = "offense", "defense", "dual"

# Kill-chain phases, in order. AVA plans across these.
PHASES = (
    "recon",            # passive + active information gathering
    "scanning",         # host/port/service discovery
    "enumeration",      # detailed service and resource enumeration
    "vuln_analysis",    # finding weaknesses
    "web",              # web application testing
    "password",         # credential attacks against authorized targets
    "wireless",         # Wi-Fi assessment
    "exploitation",     # gaining access
    "post_exploit",     # privilege escalation, lateral movement, persistence
    "c2",               # command-and-control frameworks (authorized red team)
    "forensics",        # incident response and evidence
    "reversing",        # malware analysis and reverse engineering
    "defense",          # hardening, detection, monitoring
)


@dataclass(frozen=True)
class Tool:
    name: str
    phase: str
    side: str                 # offense | defense | dual
    summary: str
    touches_target: bool      # True => needs an authorized target in scope
    platforms: tuple[str, ...] = ()
    example: str = ""         # a representative command; not executed by the catalog

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "phase": self.phase, "side": self.side,
                "summary": self.summary, "touches_target": self.touches_target,
                "platforms": list(self.platforms), "example": self.example}


def _t(name, phase, side, summary, touches, platforms=(), example=""):
    return Tool(name, phase, side, summary, touches, platforms, example)


# The catalog. Grouped by phase for readability; order within a phase is
# roughly most-reached-for first.
_TOOLS: tuple[Tool, ...] = (
    # --- recon -----------------------------------------------------------
    _t("OSINT / manual", "recon", DUAL, "Open-source intelligence: public records, DNS, certificate transparency, code search.", False),
    _t("theHarvester", "recon", OFFENSE, "Emails, subdomains and hosts from public sources.", True, example="theHarvester -d example.com -b all"),
    _t("Amass", "recon", OFFENSE, "In-depth subdomain enumeration and network mapping.", True, example="amass enum -d example.com"),
    _t("Subfinder", "recon", OFFENSE, "Fast passive subdomain discovery.", True, example="subfinder -d example.com"),
    _t("dnsrecon", "recon", OFFENSE, "DNS enumeration, zone transfers, brute force.", True, example="dnsrecon -d example.com"),
    _t("dnsx", "recon", OFFENSE, "Fast DNS toolkit for resolution and probing.", True),
    _t("Shodan", "recon", DUAL, "Search engine for internet-exposed devices and services.", False, example="shodan host 1.2.3.4"),
    _t("Censys", "recon", DUAL, "Internet-wide host and certificate intelligence.", False),
    _t("Maltego", "recon", DUAL, "Link-analysis of relationships between entities.", False),
    _t("recon-ng", "recon", OFFENSE, "Modular reconnaissance framework.", True),
    _t("whois / dig", "recon", DUAL, "Registration and DNS record lookups.", True, example="dig +short example.com any"),

    # --- scanning --------------------------------------------------------
    _t("Nmap", "scanning", DUAL, "The standard port scanner and service/OS fingerprinter, with a scripting engine (NSE).", True, ("all",), "nmap -sC -sV -oA scan 10.0.0.5"),
    _t("masscan", "scanning", OFFENSE, "Very fast port scanner for large scoped ranges.", True, example="masscan 10.0.0.0/24 -p1-65535 --rate 1000"),
    _t("Rustscan", "scanning", OFFENSE, "Fast port discovery that hands off to Nmap.", True),
    _t("naabu", "scanning", OFFENSE, "Fast SYN/CONNECT port scanner.", True),
    _t("Angry IP Scanner", "scanning", DUAL, "Lightweight host and port sweep.", True),
    _t("netdiscover", "scanning", OFFENSE, "ARP-based host discovery on a local segment.", True),

    # --- enumeration -----------------------------------------------------
    _t("enum4linux-ng", "enumeration", OFFENSE, "SMB/Windows enumeration: shares, users, policies.", True, example="enum4linux-ng -A 10.0.0.5"),
    _t("smbclient / smbmap", "enumeration", DUAL, "List and access SMB shares.", True, example="smbmap -H 10.0.0.5"),
    _t("ldapsearch", "enumeration", DUAL, "Query LDAP / Active Directory directory data.", True),
    _t("snmpwalk", "enumeration", DUAL, "Walk SNMP MIBs on networked devices.", True),
    _t("nbtscan", "enumeration", OFFENSE, "NetBIOS name enumeration.", True),
    _t("CrackMapExec / NetExec", "enumeration", OFFENSE, "Swiss-army enumeration and auth testing across AD hosts.", True, example="nxc smb 10.0.0.0/24 -u user -p pass"),
    _t("BloodHound / SharpHound", "enumeration", OFFENSE, "Maps Active Directory attack paths as a graph.", True),

    # --- vuln analysis ---------------------------------------------------
    _t("Nessus", "vuln_analysis", DEFENSE, "Commercial vulnerability scanner, broad plugin coverage.", True),
    _t("OpenVAS / Greenbone", "vuln_analysis", DEFENSE, "Open-source vulnerability scanner.", True),
    _t("Nuclei", "vuln_analysis", DUAL, "Template-driven scanner for known vulnerabilities and misconfigurations.", True, example="nuclei -u https://target -t cves/"),
    _t("nmap NSE (vuln)", "vuln_analysis", DUAL, "Nmap's vulnerability scripts.", True, example="nmap --script vuln 10.0.0.5"),
    _t("Trivy", "vuln_analysis", DEFENSE, "Scans container images, filesystems and IaC for vulnerabilities.", False),
    _t("Grype / Syft", "vuln_analysis", DEFENSE, "SBOM generation and vulnerability matching.", False),

    # --- web -------------------------------------------------------------
    _t("Burp Suite", "web", DUAL, "The standard intercepting proxy for web app testing.", True, ("all",)),
    _t("OWASP ZAP", "web", DUAL, "Open-source web app scanner and proxy.", True),
    _t("sqlmap", "web", OFFENSE, "Automated SQL-injection detection and exploitation.", True, example="sqlmap -u 'https://target/item?id=1' --batch"),
    _t("ffuf", "web", OFFENSE, "Fast web fuzzer for content and parameter discovery.", True, example="ffuf -u https://target/FUZZ -w wordlist"),
    _t("gobuster / feroxbuster", "web", OFFENSE, "Directory, file and DNS brute forcing.", True, example="gobuster dir -u https://target -w wordlist"),
    _t("Nikto", "web", OFFENSE, "Web server misconfiguration and known-issue scanner.", True),
    _t("wpscan", "web", OFFENSE, "WordPress vulnerability and plugin scanner.", True, example="wpscan --url https://target"),
    _t("XSStrike / dalfox", "web", OFFENSE, "Cross-site-scripting discovery and fuzzing.", True),
    _t("Wfuzz", "web", OFFENSE, "Web application brute forcer / fuzzer.", True),
    _t("httpx / katana", "web", DUAL, "HTTP probing and crawling for attack surface.", True),

    # --- password --------------------------------------------------------
    _t("Hashcat", "password", DUAL, "GPU password-hash cracking (offline, on hashes you are authorized to test).", False, ("all",), "hashcat -m 1000 hashes.txt wordlist"),
    _t("John the Ripper", "password", DUAL, "CPU/GPU password cracker with many formats.", False),
    _t("Hydra", "password", OFFENSE, "Online brute force against network login services.", True, example="hydra -l user -P wordlist ssh://10.0.0.5"),
    _t("Medusa", "password", OFFENSE, "Parallel network login brute forcer.", True),
    _t("Responder", "password", OFFENSE, "LLMNR/NBT-NS/mDNS poisoning to capture hashes (authorized internal only).", True),
    _t("CeWL", "password", OFFENSE, "Builds target-specific wordlists from a site.", True),
    _t("Hashcat rules / wordlists", "password", DUAL, "rockyou and rule sets for realistic cracking.", False),

    # --- wireless --------------------------------------------------------
    _t("Aircrack-ng suite", "wireless", OFFENSE, "Wi-Fi capture and WPA/WEP key recovery (your own networks).", True),
    _t("Kismet", "wireless", DUAL, "Wireless network and device detector / sniffer.", True),
    _t("Wifite", "wireless", OFFENSE, "Automated Wi-Fi auditing.", True),
    _t("hcxdumptool / hcxtools", "wireless", OFFENSE, "Capture WPA handshakes/PMKID for offline cracking.", True),
    _t("Bettercap", "wireless", OFFENSE, "Network and wireless MITM framework (authorized segments).", True),

    # --- exploitation ----------------------------------------------------
    _t("Metasploit Framework", "exploitation", DUAL, "The standard exploitation and payload framework.", True, ("all",), "msfconsole"),
    _t("searchsploit / Exploit-DB", "exploitation", DUAL, "Search a local copy of the public exploit database.", False, example="searchsploit apache 2.4"),
    _t("Impacket", "exploitation", OFFENSE, "Python classes for network protocols; the backbone of many AD attacks.", True),
    _t("evil-winrm", "exploitation", OFFENSE, "WinRM shell for authorized Windows access.", True),
    _t("msfvenom", "exploitation", DUAL, "Payload generator (for authorized engagements).", False, example="msfvenom -p windows/x64/meterpreter/reverse_tcp ..."),
    _t("PEASS-ng (winPEAS/linPEAS)", "exploitation", OFFENSE, "Local privilege-escalation enumeration scripts.", True),

    # --- post-exploitation ----------------------------------------------
    _t("Mimikatz", "post_exploit", OFFENSE, "Extracts Windows credentials from memory (authorized hosts).", True, ("windows",)),
    _t("Rubeus", "post_exploit", OFFENSE, "Kerberos abuse: kerberoasting, ticket handling.", True, ("windows",)),
    _t("BloodHound (attack paths)", "post_exploit", OFFENSE, "Plan lateral movement from mapped AD relationships.", True),
    _t("Sliver", "c2", OFFENSE, "Open-source command-and-control for authorized red teaming.", True),
    _t("Cobalt Strike", "c2", OFFENSE, "Commercial red-team C2 (licensed, authorized engagements).", True),
    _t("Covenant / Mythic", "c2", OFFENSE, "Post-exploitation C2 frameworks.", True),
    _t("chisel / ligolo-ng", "post_exploit", OFFENSE, "Tunnelling and pivoting through an authorized foothold.", True),

    # --- forensics & IR (defense) ---------------------------------------
    _t("Volatility 3", "forensics", DEFENSE, "Memory forensics: processes, injected code, artifacts.", False),
    _t("Autopsy / Sleuth Kit", "forensics", DEFENSE, "Disk forensics and timeline analysis.", False),
    _t("Wireshark / tshark", "forensics", DUAL, "Packet capture and deep protocol analysis.", True, ("all",), "tshark -i eth0 -f 'host 10.0.0.5'"),
    _t("Zeek", "forensics", DEFENSE, "Network security monitoring and connection logging.", False),
    _t("YARA", "forensics", DEFENSE, "Pattern-matching to classify and identify malware.", False, example="yara rules.yar sample"),
    _t("chainsaw / hayabusa", "forensics", DEFENSE, "Fast triage of Windows event logs against detection rules.", False),
    _t("velociraptor", "forensics", DEFENSE, "Endpoint visibility and DFIR at scale.", False),

    # --- reversing -------------------------------------------------------
    _t("Ghidra", "reversing", DEFENSE, "NSA's open-source reverse-engineering suite / decompiler.", False),
    _t("IDA / Binary Ninja", "reversing", DUAL, "Interactive disassemblers/decompilers.", False),
    _t("radare2 / rizin", "reversing", DUAL, "Command-line reverse-engineering framework.", False),
    _t("x64dbg / gdb-pwndbg", "reversing", DUAL, "Debuggers for dynamic analysis.", False),
    _t("pwntools", "reversing", OFFENSE, "CTF/exploit-development toolkit.", False),
    _t("angr", "reversing", DUAL, "Binary analysis and symbolic execution.", False),

    # --- defense ---------------------------------------------------------
    _t("Sigma", "defense", DEFENSE, "Vendor-neutral detection rules for SIEMs.", False),
    _t("Suricata / Snort", "defense", DEFENSE, "Network IDS/IPS.", False),
    _t("osquery", "defense", DEFENSE, "Query endpoint state like a database, for detection and audit.", False),
    _t("Wazuh", "defense", DEFENSE, "Open-source SIEM/XDR: log analysis, FIM, detection.", False),
    _t("Lynis", "defense", DEFENSE, "Host hardening and compliance auditing.", False, ("linux", "macos"), "lynis audit system"),
    _t("CIS Benchmarks / OpenSCAP", "defense", DEFENSE, "Configuration hardening standards and scanners.", False),
    _t("fail2ban", "defense", DEFENSE, "Bans hosts that show malicious sign-in patterns.", False),
    _t("Atomic Red Team", "defense", DEFENSE, "Runs known attack techniques to test your detections.", True),
    _t("Windows Defender / EDR tuning", "defense", DEFENSE, "Endpoint protection configuration and detection review.", False),
)


def phases() -> tuple[str, ...]:
    return PHASES


def tools(*, phase: str = "", side: str = "") -> list[Tool]:
    result = list(_TOOLS)
    if phase:
        result = [t for t in result if t.phase == phase]
    if side:
        result = [t for t in result if t.side == side or (side == DUAL and t.side == DUAL)]
    return result


def find(query: str) -> list[Tool]:
    q = str(query or "").strip().casefold()
    if not q:
        return []
    return [t for t in _TOOLS
            if q in t.name.casefold() or q in t.summary.casefold() or q == t.phase]


def summary() -> dict[str, Any]:
    by_phase: dict[str, int] = {}
    by_side: dict[str, int] = {}
    for tool in _TOOLS:
        by_phase[tool.phase] = by_phase.get(tool.phase, 0) + 1
        by_side[tool.side] = by_side.get(tool.side, 0) + 1
    return {"total": len(_TOOLS), "phases": list(PHASES),
            "by_phase": by_phase, "by_side": by_side,
            "offensive": by_side.get(OFFENSE, 0) + by_side.get(DUAL, 0),
            "defensive": by_side.get(DEFENSE, 0) + by_side.get(DUAL, 0)}
