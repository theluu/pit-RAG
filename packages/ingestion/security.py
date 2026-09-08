import io

import clamd

from apps.api.config import settings


def scan_upload(data: bytes) -> None:
    scanner = clamd.ClamdNetworkSocket(settings.clamav_host, settings.clamav_port, timeout=10)
    try:
        result = scanner.instream(io.BytesIO(data))
    except (OSError, ConnectionError):
        if settings.malware_scan_required:
            raise RuntimeError("Malware scanner unavailable")
        return
    status = next(iter(result.values()))[0] if result else "ERROR"
    if status != "OK":
        raise ValueError("Upload rejected by malware scanner")
