from __future__ import annotations

from copy import deepcopy
from typing import Any

from .errors import PolicyError

TEMPLATES: dict[str, dict[str, Any]] = {
    "generic-socks-proxy": {
        "name": "generic-socks-proxy",
        "provider": "generic",
        "summary": "Use any verified local or sidecar SOCKS proxy.",
        "profile": {
            "type": "proxy",
            "proxy": "socks5h://127.0.0.1:1080",
            "enabled": False,
            "description": "Generic SOCKS egress. Enable only after verify_egress_profile passes.",
        },
        "notes": [
            "Use socks5h so DNS resolution happens through the proxy.",
            "Keep require_proxy=true for this template.",
            "Set proxy to the address exposed by your VPN or proxy sidecar.",
        ],
    },
    "gluetun-wireguard-socks": {
        "name": "gluetun-wireguard-socks",
        "provider": "wireguard",
        "summary": "Run a WireGuard-capable VPN sidecar that exposes a local SOCKS5 proxy.",
        "profile": {
            "type": "proxy",
            "proxy": "socks5h://127.0.0.1:1080",
            "enabled": False,
            "description": "WireGuard VPN sidecar SOCKS egress. Verify before activation.",
        },
        "compose_service": {
            "vpn-proxy": {
                "image": "qmcgaw/gluetun:latest",
                "cap_add": ["NET_ADMIN"],
                "environment": {
                    "VPN_SERVICE_PROVIDER": "<provider>",
                    "VPN_TYPE": "wireguard",
                    "WIREGUARD_PRIVATE_KEY": "<secret>",
                    "WIREGUARD_ADDRESSES": "<address>",
                    "SOCKS5": "on",
                    "SOCKS5_LISTENING_ADDRESS": ":1080",
                },
                "ports": ["127.0.0.1:1080:1080/tcp"],
            }
        },
        "notes": [
            "This template is provider-agnostic for VPNs supported by gluetun.",
            "Keep secrets out of the MCP config; put them in the sidecar environment.",
            "Expose the proxy only on localhost or an internal Docker network.",
        ],
    },
    "expressvpn-process-vpn": {
        "name": "expressvpn-process-vpn",
        "provider": "expressvpn",
        "summary": "Document a process/container-level ExpressVPN route when no proxy is exposed.",
        "profile": {
            "type": "external_vpn",
            "enabled": False,
            "description": (
                "ExpressVPN process/container route. Enable only after egress IP is verified."
            ),
        },
        "notes": [
            "ExpressVPN Lightway does not normally expose a SOCKS proxy endpoint.",
            "This profile cannot satisfy require_proxy=true.",
            (
                "Only activate with allow_external_vpn_without_proxy after process-level "
                "routing is verified."
            ),
        ],
    },
}


def list_egress_templates(provider: str | None = None) -> dict[str, Any]:
    normalized_provider = (provider or "").strip().lower()
    templates = []
    for template in TEMPLATES.values():
        if normalized_provider and template["provider"] != normalized_provider:
            continue
        templates.append(_summary(template))
    return {"templates": templates}


def get_egress_template(name: str) -> dict[str, Any]:
    key = (name or "").strip()
    template = TEMPLATES.get(key)
    if template is None:
        raise PolicyError(f"Unknown egress template: {name}")
    return deepcopy(template)


def render_profile_from_template(
    name: str,
    *,
    profile_name: str,
    proxy: str | None = None,
) -> dict[str, Any]:
    template = get_egress_template(name)
    normalized_profile_name = (profile_name or "").strip()
    if not normalized_profile_name:
        raise PolicyError("profile_name is required.")
    profile = deepcopy(template["profile"])
    if proxy is not None:
        profile["proxy"] = proxy
    return {
        "name": normalized_profile_name,
        "profile": profile,
        "config_patch": {
            "egress_profiles": {
                normalized_profile_name: profile,
            }
        },
        "notes": template["notes"],
    }


def _summary(template: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": template["name"],
        "provider": template["provider"],
        "summary": template["summary"],
        "profile_type": template["profile"]["type"],
    }
