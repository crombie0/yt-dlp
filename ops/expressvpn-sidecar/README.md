# ExpressVPN Sidecar Proxy

This sidecar keeps ExpressVPN out of the host network stack. It runs ExpressVPN
inside a dedicated container, starts a local SOCKS5 proxy, and lets the yt-dlp
MCP use only `socks5h://127.0.0.1:1080`.

## Required private files

ExpressVPN distributes the Linux installer from the authenticated setup page.
Download the Linux Universal Installer from your account and place it here:

```bash
/home/crombie/expressvpn-sidecar/installer/expressvpn-linux-*.run
```

Then create the activation code file on the server. Do not paste the activation
code into chat or commit it to git.

```bash
install -d -m 700 /home/crombie/expressvpn-sidecar/secrets
printf '%s\n' 'YOUR_ACTIVATION_CODE' > /home/crombie/expressvpn-sidecar/secrets/activation_code
chmod 600 /home/crombie/expressvpn-sidecar/secrets/activation_code
```

## Start

```bash
cd /home/crombie/expressvpn-sidecar
docker compose up -d --build
```

## Verify

```bash
docker logs --tail 100 expressvpn-proxy
curl --socks5-hostname 127.0.0.1:1080 https://api.ipify.org?format=json
```

After the proxy returns a VPN IP, verify and activate the MCP profile:

```bash
# via MCP:
# verify_egress_profile(profile_name="vpn-proxy", expected_ip="<observed-ip>")
# activate_egress_profile(profile_name="vpn-proxy")
```

## Notes

- The proxy is bound to `127.0.0.1:1080` on the host, not exposed publicly.
- `EXPRESSVPN_PROTOCOL` defaults to `lightwayudp`.
- Set `EXPRESSVPN_LOCATION` in `.env` or `compose.yml` to pin a region.
- Keep `YTDLP_MCP_REQUIRE_PROXY=true` in the MCP config.
