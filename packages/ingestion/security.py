import io

import clamd

from apps.api.config import settings


def scan_upload(data: bytes) -> None:
    scanner = clamd.ClamdNetworkSocket(settings.clamav_host, settings.clamav_port, timeout=10)
    try:
        result = scanner.instream(io.BytesIO(data))
    except (OSError, clamd.ClamdError):
        # clamd.ConnectionError descends from ClamdError, not from the builtin
        # ConnectionError, so catching the builtin here let a missing scanner turn
        # every upload into a 500. ClamdError covers the response and buffer errors
        # too: if the scan cannot complete, the policy flag decides, not the cause.
        if settings.malware_scan_required:
            raise RuntimeError("Malware scanner unavailable")
        return
    status = next(iter(result.values()))[0] if result else "ERROR"
    if status != "OK":
        raise ValueError("Upload rejected by malware scanner")
