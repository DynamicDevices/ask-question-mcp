"""YubiKey-touch send capability minting for Briar P0 Send-now gates.

Mint only after a successful desktop Send-now selection. Signing uses an
enrolled OpenSSH FIDO SK private key (physical touch). The capability blob
never leaves a mode-0600 sidecar path in MCP/tool results.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

NAMESPACE = "briar-send-cap"
CAP_VERSION = 1
DEFAULT_TTL_S = 90
ALLOWED_SERIALS = ("38907480", "38907389")
DEFAULT_SK_KEY = Path.home() / ".ssh" / "id_ed25519_sk_breakglass"
DEFAULT_CAP_DIR = Path.home() / ".local" / "share" / "whatsapp-mcp" / "send-caps"
SERIAL_MAP_PATH = Path.home() / ".config" / "cursorpa" / "send-cap-keys.json"
DEFAULT_ASKPASS = (
    Path.home()
    / ".cursor"
    / "skills"
    / "cursor-pa-whatsapp"
    / "scripts"
    / "briar-ssh-askpass-gui.sh"
)
DEFAULT_AGENT_SOCK = Path(f"/run/user/{os.getuid()}/briar-send-cap/agent.sock")


class SendCapError(Exception):
    """Fail-closed mint failure (no capability file)."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_jid(raw: str) -> str:
    j = (raw or "").strip().lower()
    if not j:
        return ""
    if "@" not in j:
        j = f"{j}@s.whatsapp.net"
    return j


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_request_fields(req: Mapping[str, Any]) -> Dict[str, Any]:
    """Stable subset used for request_hash (sorted keys when dumped)."""
    op = str(req.get("op") or "send").strip().lower()
    out: Dict[str, Any] = {
        "op": op,
        "recipient": normalize_jid(str(req.get("recipient") or "")),
        "message": str(req.get("message") or ""),
        "quoted_message_id": str(req.get("quoted_message_id") or ""),
        "quoted_sender_jid": normalize_jid(str(req.get("quoted_sender_jid") or "")),
        "quoted_content": str(req.get("quoted_content") or ""),
        "mentions": [
            normalize_jid(str(m))
            for m in (req.get("mentions") or [])
            if str(m).strip()
        ],
        "media_path": str(req.get("media_path") or ""),
        "message_id": str(req.get("message_id") or ""),
        "emoji": str(req.get("emoji") if req.get("emoji") is not None else ""),
        "from_me": bool(req.get("from_me") or False),
        "sender_jid": normalize_jid(str(req.get("sender_jid") or "")),
    }
    return out


def request_hash(req: Mapping[str, Any]) -> str:
    payload = canonical_request_fields(req)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_hex(raw.encode("utf-8"))


def media_hash_for_request(req: Mapping[str, Any]) -> str:
    path = str(req.get("media_path") or "").strip()
    if not path:
        return ""
    p = Path(path)
    if not p.is_file():
        raise SendCapError(f"media_path not a file: {path}")
    return sha256_file(p)


def lease_token_hash(token: str) -> str:
    token = (token or "").strip()
    if not token:
        return ""
    return sha256_hex(token.encode("utf-8"))


def list_yubikey_serials(
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> list[str]:
    run = runner or subprocess.run
    try:
        proc = run(
            ["ykman", "list", "--serials"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        raise SendCapError(f"ykman unavailable: {exc}") from exc
    if proc.returncode != 0:
        raise SendCapError(
            f"ykman list failed: {(proc.stderr or proc.stdout or '').strip()}"
        )
    serials = []
    for line in (proc.stdout or "").splitlines():
        s = line.strip()
        if s.isdigit():
            serials.append(s)
    return serials


def pick_allowed_serial(present: Sequence[str]) -> str:
    allowed = set(ALLOWED_SERIALS)
    for serial in present:
        if serial in allowed:
            return serial
    raise SendCapError(
        "no approved YubiKey present "
        f"(need one of {', '.join(ALLOWED_SERIALS)}; found {list(present) or 'none'})"
    )


def load_key_map(path: Path = SERIAL_MAP_PATH) -> Dict[str, Any]:
    if not path.is_file():
        return {
            "namespace": NAMESPACE,
            "keys": [
                {
                    "serial": "38907480",
                    "key_id": "alex-yk5c-breakglass-sn38907480",
                    "private_key_path": str(DEFAULT_SK_KEY),
                    "public_key_path": str(DEFAULT_SK_KEY.with_suffix(".pub")),
                }
            ],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SendCapError(f"send-cap key map unreadable: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
        raise SendCapError("send-cap key map malformed")
    return data


def key_for_serial(serial: str, key_map: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    data = key_map or load_key_map()
    for row in data.get("keys") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("serial") or "") == serial:
            return row
    raise SendCapError(f"no enrolled send-cap signing key for serial {serial}")


def build_capability(
    req: Mapping[str, Any],
    *,
    yk_serial: str,
    key_id: str,
    ttl_s: int = DEFAULT_TTL_S,
    now: Optional[datetime] = None,
    nonce: Optional[str] = None,
) -> Dict[str, Any]:
    op = str(req.get("op") or "send").strip().lower()
    if op not in ("send", "react"):
        raise SendCapError(f"unsupported op: {op}")
    recipient = normalize_jid(str(req.get("recipient") or ""))
    if not recipient:
        raise SendCapError("recipient required")
    when = now or _utc_now()
    exp = when + timedelta(seconds=max(5, int(ttl_s)))
    lease = str(req.get("lease_owner_token") or "")
    return {
        "v": CAP_VERSION,
        "op": op,
        "recipient": recipient,
        "request_hash": request_hash(req),
        "media_hash": media_hash_for_request(req),
        "lease_token_hash": lease_token_hash(lease),
        "iat": _iso(when),
        "exp": _iso(exp),
        "nonce": nonce or secrets.token_urlsafe(16),
        "yk_serial": yk_serial,
        "key_id": key_id,
    }


def capability_signing_bytes(cap: Mapping[str, Any]) -> bytes:
    return json.dumps(cap, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _agent_socket() -> Optional[Path]:
    """Return Briar's native OpenSSH agent socket.

    GCR may list FIDO SK keys but refuses ``ssh-keygen -Y sign`` operations,
    so send-cap minting deliberately uses its own OpenSSH agent.
    """
    candidates = [
        os.environ.get("BRIAR_SEND_CAP_SSH_AUTH_SOCK"),
        str(DEFAULT_AGENT_SOCK),
    ]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw)
        if path.exists():
            return path
    return None


def signing_env() -> Dict[str, str]:
    """Environment for ssh-keygen so any passphrase prompt is a desktop dialog.

    The key handle passphrase must never be typed into chat or passed on the
    command line, so SSH_ASKPASS is forced even when a tty is attached.
    """
    env = dict(os.environ)
    agent_sock = _agent_socket()
    if agent_sock:
        env["SSH_AUTH_SOCK"] = str(agent_sock)
    askpass = env.get("BRIAR_SEND_CAP_ASKPASS") or str(DEFAULT_ASKPASS)
    if Path(askpass).is_file() and os.access(askpass, os.X_OK):
        env["SSH_ASKPASS"] = askpass
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env.setdefault("DISPLAY", ":0")
    return env


def _public_key_parts(path: Path) -> Tuple[str, str]:
    try:
        parts = path.read_text(encoding="utf-8").split()
    except OSError as exc:
        raise SendCapError(f"public signing key unreadable: {path}") from exc
    if len(parts) < 2:
        raise SendCapError(f"public signing key malformed: {path}")
    return parts[0], parts[1]


def agent_has_key(
    public_key: Path,
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> bool:
    """Check whether the exact public key is loaded; never expose key material."""
    if not _agent_socket():
        return False
    run = runner or subprocess.run
    try:
        proc = run(
            ["ssh-add", "-L"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=signing_env(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    if proc.returncode != 0:
        return False
    wanted = _public_key_parts(public_key)
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and (parts[0], parts[1]) == wanted:
            return True
    return False


def signing_key_for_agent(
    private_key: Path,
    public_key: Path,
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
) -> Path:
    """Load the encrypted SK handle once, then return its public-key path.

    OpenSSH accepts a public key for ``ssh-keygen -Y sign`` when the matching
    private key is in ssh-agent. Loading prompts for the passphrase through the
    desktop askpass helper; each actual signature still requires FIDO touch.
    """
    # Injected runners are unit-test fakes for the signing operation itself.
    # They should not need to emulate the host ssh-agent.
    if runner is not None:
        return private_key
    if not public_key.is_file() or not _agent_socket():
        return private_key
    if agent_has_key(public_key):
        return public_key
    try:
        proc = subprocess.run(
            ["ssh-add", str(private_key)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env=signing_env(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        raise SendCapError(f"ssh-agent key load failed: {exc}") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise SendCapError(f"ssh-agent key load failed: {err or 'cancelled'}")
    if not agent_has_key(public_key):
        raise SendCapError("ssh-agent did not retain the enrolled signing key")
    return public_key


def ssh_sign(
    message: bytes,
    signing_key: Path,
    *,
    namespace: str = NAMESPACE,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    timeout_s: int = 120,
) -> str:
    """Sign with OpenSSH (FIDO SK keys prompt for touch). Returns signature armor."""
    run = runner or subprocess.run
    if not signing_key.is_file():
        raise SendCapError(f"signing key missing: {signing_key}")
    with tempfile.TemporaryDirectory(prefix="briar-send-cap-") as tmp:
        msg_path = Path(tmp) / "payload"
        msg_path.write_bytes(message)
        proc = run(
            [
                "ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(signing_key),
                "-n",
                namespace,
                str(msg_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=signing_env(),
        )
        sig_path = Path(str(msg_path) + ".sig")
        if proc.returncode != 0 or not sig_path.is_file():
            err = (proc.stderr or proc.stdout or "").strip()
            raise SendCapError(f"YubiKey touch/sign failed: {err or 'no signature'}")
        return sig_path.read_text(encoding="utf-8")


def write_capability_sidecar(
    cap: Mapping[str, Any],
    signature: str,
    *,
    directory: Optional[Path] = None,
) -> Path:
    directory = directory or DEFAULT_CAP_DIR
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    fd, raw = tempfile.mkstemp(prefix="cap-", suffix=".json", dir=str(directory))
    path = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "namespace": NAMESPACE,
                    "capability": cap,
                    "signature": signature,
                },
                handle,
                indent=2,
                ensure_ascii=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, 0o600)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def is_send_now_gate(
    *,
    dangerous: bool,
    action_class: Optional[str],
    allow_multiple: bool,
    options: Sequence[Mapping[str, Any]],
    selected_ids: Sequence[str],
) -> bool:
    if not dangerous:
        return False
    if (action_class or "").strip().lower() != "comms":
        return False
    if allow_multiple:
        return False
    if list(selected_ids) != ["send_now"]:
        return False
    ids = {str(o.get("id") or "") for o in options if isinstance(o, dict)}
    return {"send_now", "hold", "edit"}.issubset(ids)


def maybe_mint_send_capability(
    *,
    dangerous: bool,
    action_class: Optional[str],
    allow_multiple: bool,
    options: Sequence[Mapping[str, Any]],
    selected_ids: Sequence[str],
    send_cap_request: Optional[Mapping[str, Any]],
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    key_map: Optional[Mapping[str, Any]] = None,
    cap_dir: Optional[Path] = None,
    ttl_s: int = DEFAULT_TTL_S,
    now: Optional[datetime] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Return (send_capability_file, error_reason).

    On non-send_now outcomes: (None, None).
    On send_now success: (path, None).
    On send_now failure: (None, reason) — still returns selected_ids to caller.
    """
    if not is_send_now_gate(
        dangerous=dangerous,
        action_class=action_class,
        allow_multiple=allow_multiple,
        options=options,
        selected_ids=selected_ids,
    ):
        return None, None
    if not isinstance(send_cap_request, Mapping) or not send_cap_request:
        return None, "send_cap_request required for Send now"
    try:
        present = list_yubikey_serials(runner=runner)
        serial = pick_allowed_serial(present)
        row = key_for_serial(serial, key_map=key_map)
        key_id = str(row.get("key_id") or f"serial-{serial}")
        priv = Path(
            str(
                row.get("private_key_path")
                or os.environ.get("BRIAR_SEND_CAP_SIGN_KEY")
                or DEFAULT_SK_KEY
            )
        )
        pub = Path(str(row.get("public_key_path") or priv.with_suffix(".pub")))
        signing_key = signing_key_for_agent(priv, pub, runner=runner)
        cap = build_capability(
            send_cap_request,
            yk_serial=serial,
            key_id=key_id,
            ttl_s=ttl_s,
            now=now,
        )
        signature = ssh_sign(
            capability_signing_bytes(cap),
            signing_key,
            runner=runner,
        )
        path = write_capability_sidecar(cap, signature, directory=cap_dir)
        return str(path), None
    except SendCapError as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 — fail closed
        return None, f"send capability mint failed: {exc}"
