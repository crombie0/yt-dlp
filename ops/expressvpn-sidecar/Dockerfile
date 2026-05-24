FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        iproute2 \
        iptables \
        kmod \
        microsocks \
        procps \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/expressvpn-sidecar-entrypoint
COPY healthcheck.sh /usr/local/bin/expressvpn-sidecar-healthcheck

RUN chmod +x \
        /usr/local/bin/expressvpn-sidecar-entrypoint \
        /usr/local/bin/expressvpn-sidecar-healthcheck

EXPOSE 1080/tcp

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD /usr/local/bin/expressvpn-sidecar-healthcheck

ENTRYPOINT ["/usr/local/bin/expressvpn-sidecar-entrypoint"]
