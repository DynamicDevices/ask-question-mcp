#!/usr/bin/env python3
"""Unit tests for Briar send-capability minting (no live YubiKey required)."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from ask_question_mcp import send_capability as sc


SEND_NOW_OPTS = [
    {"id": "send_now", "label": "Send now"},
    {"id": "hold", "label": "Hold"},
    {"id": "edit", "label": "Edit"},
]


class FakeRunner:
    def __init__(self, serials: list[str], sign_ok: bool = True):
        self.serials = serials
        self.sign_ok = sign_ok
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):  # noqa: ANN001
        self.calls.append(list(argv))
        if argv[:3] == ["ykman", "list", "--serials"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout="\n".join(self.serials) + "\n", stderr=""
            )
        if argv[:3] == ["ssh-keygen", "-Y", "sign"]:
            if not self.sign_ok:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="touch cancelled")
            msg = Path(argv[-1])
            sig = Path(str(msg) + ".sig")
            sig.write_text(
                "-----BEGIN SSH SIGNATURE-----\nTEST\n-----END SSH SIGNATURE-----\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected")


class SendCapTests(unittest.TestCase):
    def test_gate_detection(self) -> None:
        self.assertTrue(
            sc.is_send_now_gate(
                dangerous=True,
                action_class="comms",
                allow_multiple=False,
                options=SEND_NOW_OPTS,
                selected_ids=["send_now"],
            )
        )
        self.assertFalse(
            sc.is_send_now_gate(
                dangerous=True,
                action_class="comms",
                allow_multiple=False,
                options=SEND_NOW_OPTS,
                selected_ids=["hold"],
            )
        )

    def test_request_hash_stable(self) -> None:
        req = {
            "op": "send",
            "recipient": "447700900123",
            "message": "hello",
            "mentions": [],
        }
        a = sc.request_hash(req)
        b = sc.request_hash(dict(req))
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)

    def test_mint_requires_yubikey(self) -> None:
        path, err = sc.maybe_mint_send_capability(
            dangerous=True,
            action_class="comms",
            allow_multiple=False,
            options=SEND_NOW_OPTS,
            selected_ids=["send_now"],
            send_cap_request={"op": "send", "recipient": "1@s.whatsapp.net", "message": "x"},
            runner=FakeRunner([]),
        )
        self.assertIsNone(path)
        self.assertIn("no approved YubiKey", err or "")

    def test_mint_success_writes_0600_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            priv = Path(tmp) / "id_ed25519_sk"
            priv.write_text("dummy", encoding="utf-8")
            key_map = {
                "keys": [
                    {
                        "serial": "38907480",
                        "key_id": "test-key",
                        "private_key_path": str(priv),
                    }
                ]
            }
            cap_dir = Path(tmp) / "caps"
            path, err = sc.maybe_mint_send_capability(
                dangerous=True,
                action_class="comms",
                allow_multiple=False,
                options=SEND_NOW_OPTS,
                selected_ids=["send_now"],
                send_cap_request={
                    "op": "send",
                    "recipient": "447478346120@s.whatsapp.net",
                    "message": "probe",
                },
                runner=FakeRunner(["38907480"]),
                key_map=key_map,
                cap_dir=cap_dir,
                now=datetime(2026, 8, 15, 8, 0, 0, tzinfo=timezone.utc),
            )
            self.assertIsNone(err)
            self.assertIsNotNone(path)
            assert path is not None
            st = Path(path).stat()
            self.assertEqual(st.st_mode & 0o777, 0o600)
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(data["capability"]["yk_serial"], "38907480")
            self.assertIn("BEGIN SSH SIGNATURE", data["signature"])
            # never put private material fields
            self.assertNotIn("private_key", json.dumps(data))

    def test_hold_does_not_mint(self) -> None:
        path, err = sc.maybe_mint_send_capability(
            dangerous=True,
            action_class="comms",
            allow_multiple=False,
            options=SEND_NOW_OPTS,
            selected_ids=["hold"],
            send_cap_request={"op": "send", "recipient": "1@s.whatsapp.net", "message": "x"},
            runner=FakeRunner(["38907480"]),
        )
        self.assertIsNone(path)
        self.assertIsNone(err)

    def test_touch_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            priv = Path(tmp) / "key"
            priv.write_text("x", encoding="utf-8")
            path, err = sc.maybe_mint_send_capability(
                dangerous=True,
                action_class="comms",
                allow_multiple=False,
                options=SEND_NOW_OPTS,
                selected_ids=["send_now"],
                send_cap_request={"op": "send", "recipient": "1@s.whatsapp.net", "message": "x"},
                runner=FakeRunner(["38907480"], sign_ok=False),
                key_map={
                    "keys": [
                        {
                            "serial": "38907480",
                            "key_id": "t",
                            "private_key_path": str(priv),
                        }
                    ]
                },
                cap_dir=Path(tmp) / "caps",
            )
            self.assertIsNone(path)
            self.assertIn("touch/sign failed", err or "")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
