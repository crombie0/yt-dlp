FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        iproute2 \
        iptables \
        kmod \
        libatomic1 \
        libglib2.0-0 \
        libnl-3-200 \
        libnl-route-3-200 \
        microsocks \
        psmisc \
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
