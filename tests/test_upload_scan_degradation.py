"""Uploads must survive a missing malware scanner when scanning is not required.

Reproduces a 500 on the dev deployment: every PDF upload failed with

    clamd.ConnectionError: Error 111 connecting localhost:3310. Connection refused.

ClamAV is not installed there and MALWARE_SCAN_REQUIRED is false, so scan_upload was
meant to skip the scan and return. It could not: `clamd.ConnectionError` descends from
`ClamdError -> Exception`, NOT from the builtin `ConnectionError`, and the module
imports `clamd` as a namespace — so the bare `ConnectionError` in the except clause
resolved to the builtin and never matched.
"""

import clamd
import pytest

from apps.api.config import settings
from packages.ingestion import security


def refuse(*_args, **_kwargs):
    raise clamd.ConnectionError("Error 111 connecting localhost:3310. Connection refused.")


@pytest.fixture
def scanner(monkeypatch):
    """Swap the socket for a stub so no test ever needs a live clamd."""
    calls = {}

    class Stub:
        def __init__(self, *args, **kwargs):
            pass

        def instream(self, stream):
            return calls["instream"](stream)

    monkeypatch.setattr(clamd, "ClamdNetworkSocket", Stub)
    return calls


def test_clamd_connection_error_is_skipped_when_scanning_is_optional(scanner, monkeypatch):
    monkeypatch.setattr(settings, "malware_scan_required", False)
    scanner["instream"] = refuse

    assert security.scan_upload(b"%PDF-1.7 ...") is None


def test_clamd_connection_error_still_blocks_when_scanning_is_required(scanner, monkeypatch):
    monkeypatch.setattr(settings, "malware_scan_required", True)
    scanner["instream"] = refuse

    with pytest.raises(RuntimeError, match="unavailable"):
        security.scan_upload(b"%PDF-1.7 ...")


@pytest.mark.parametrize("failure", [
    clamd.ConnectionError("refused"),
    clamd.BufferTooLongError("too long"),
    clamd.ResponseError("garbled"),
    OSError("socket gone"),
    ConnectionRefusedError(111, "Connection refused"),
])
def test_every_scanner_failure_degrades_the_same_way(scanner, monkeypatch, failure):
    monkeypatch.setattr(settings, "malware_scan_required", False)

    def raise_it(_stream):
        raise failure

    scanner["instream"] = raise_it
    assert security.scan_upload(b"%PDF-1.7 ...") is None


def test_a_clean_file_passes(scanner, monkeypatch):
    monkeypatch.setattr(settings, "malware_scan_required", False)
    scanner["instream"] = lambda _s: {"stream": ("OK", None)}

    assert security.scan_upload(b"%PDF-1.7 ...") is None


def test_an_infected_file_is_rejected_even_when_scanning_is_optional(scanner, monkeypatch):
    monkeypatch.setattr(settings, "malware_scan_required", False)
    scanner["instream"] = lambda _s: {"stream": ("FOUND", "Eicar-Test-Signature")}

    with pytest.raises(ValueError, match="rejected"):
        security.scan_upload(b"eicar")


def test_an_empty_scanner_response_is_treated_as_a_rejection(scanner, monkeypatch):
    monkeypatch.setattr(settings, "malware_scan_required", False)
    scanner["instream"] = lambda _s: {}

    with pytest.raises(ValueError, match="rejected"):
        security.scan_upload(b"%PDF-1.7 ...")
