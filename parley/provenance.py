"""Hash-chained AND Ed25519-SIGNED provenance for a bilateral negotiation.

Parley records EVERY governance step (request, consent, counter, human-approve,
capability-run, DP-charge, checker-verdict) in a hash CHAIN where each link commits to the prior
hash AND is signed with the data owner's Ed25519 key. A bare hash chain is only
tamper-EVIDENT against accidental corruption: an adversary can edit a step and
recompute every forward hash. The signature closes that hole — forging a receipt
now requires the owner's PRIVATE key, while a third party (the other org, a judge,
an auditor) re-attests every receipt against the published PUBLIC key with zero
trust in Parley and no shared secret.

Key handling: a real deployment binds the owner's KMS/HSM key to its Band identity
and a verifier PINS that published public key (pass ``owner_pubkey`` to
``verify_chain``). The demo generates an ephemeral per-deal owner key and publishes
its public half in the bundle, so tampering-without-the-key is caught out of the box.

Stdlib hashing; Ed25519 via ``cryptography`` (a base dependency). Signing degrades
gracefully to unsigned if the library is somehow absent. No band import.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

GENESIS = "0" * 64

# The owner's PRIVATE signing key (gitignored) and the PUBLIC key a verifier pins
# out-of-band (committed). Verification trusts the pinned public key, not whatever
# key a bundle publishes about itself — so a full re-sign forgery cannot pass.
OWNER_PRIV_PATH = os.environ.get("PARLEY_OWNER_KEY", ".parley_owner_key.hex")
OWNER_PUB_PATH = os.environ.get("PARLEY_OWNER_PUBKEY", "proof/owner_pubkey.hex")


def _ed25519():
    """Lazy import so the module stays importable even without cryptography."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
        return ed25519, serialization
    except Exception:  # pragma: no cover - cryptography is a base dep
        return None, None


def generate_signing_key() -> Any:
    """A fresh Ed25519 private key (the data owner's signing key). None if unavailable."""
    ed25519, _ = _ed25519()
    return ed25519.Ed25519PrivateKey.generate() if ed25519 else None


def public_key_hex(private_key: Any) -> str:
    """Raw 32-byte Ed25519 public key as hex (published in the bundle)."""
    _, serialization = _ed25519()
    raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return raw.hex()


def _harden_key_perms(path: str) -> None:
    """Restrict a private-key file to owner-only (0o600). No-op on Windows (ACL-based)."""
    if os.name == "nt":
        return
    try:
        if (os.stat(path).st_mode & 0o077) != 0:
            os.chmod(path, 0o600)
    except OSError:
        pass


def _write_private_key_secure(priv_path: str, hex_data: str) -> None:
    """Atomically create the private-key file readable/writable by the owner only.

    O_EXCL prevents a symlink/pre-existing-file race; mode 0o600 means no group/other
    access from creation (not chmod-after, which would leave a readable window).
    """
    fd = os.open(priv_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(hex_data)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def load_or_create_owner_key(priv_path: str = OWNER_PRIV_PATH,
                             pub_path: str = OWNER_PUB_PATH) -> Any:
    """Load the owner's PERSISTENT Ed25519 private key (create + persist on first use).

    The private key stays in a gitignored, owner-only (0o600) file; its public half is
    written to a committed file so a third party can PIN it out-of-band. Persistence is
    what makes the signature meaningful across runs — an ephemeral per-deal key can't be
    pinned. Returns None if cryptography is unavailable.
    """
    ed25519, serialization = _ed25519()
    if ed25519 is None:
        return None
    try:
        if os.path.exists(priv_path):
            _harden_key_perms(priv_path)  # tighten perms on a pre-existing key too
            key = ed25519.Ed25519PrivateKey.from_private_bytes(
                bytes.fromhex(open(priv_path, encoding="utf-8").read().strip()))
        else:
            new = ed25519.Ed25519PrivateKey.generate()
            raw = new.private_bytes(serialization.Encoding.Raw,
                                    serialization.PrivateFormat.Raw,
                                    serialization.NoEncryption())
            try:
                _write_private_key_secure(priv_path, raw.hex())
                key = new
            except FileExistsError:  # lost a create race -> read the winner
                _harden_key_perms(priv_path)
                key = ed25519.Ed25519PrivateKey.from_private_bytes(
                    bytes.fromhex(open(priv_path, encoding="utf-8").read().strip()))
        pub = public_key_hex(key)
        if pub_path:  # public key — not sensitive, normal perms are fine
            d = os.path.dirname(pub_path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(pub_path, "w", encoding="utf-8") as f:
                f.write(pub)
        return key
    except OSError:  # read-only fs etc. -> fall back to an ephemeral key
        return generate_signing_key()


def load_pinned_pubkey(pub_path: str = OWNER_PUB_PATH) -> Optional[str]:
    """The owner public key a verifier pins out-of-band (None if not available)."""
    try:
        return (open(pub_path, encoding="utf-8").read().strip() or None)
    except OSError:
        return None


def _load_pub(pub_hex: str) -> Any:
    ed25519, _ = _ed25519()
    if not (ed25519 and pub_hex):
        return None
    return ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))


def _canonical(obj: Any) -> str:
    """Deterministic JSON for hashing (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(prev_hash: str, seq: int, step: dict) -> str:
    return hashlib.sha256(f"{prev_hash}|{seq}|{_canonical(step)}".encode("utf-8")).hexdigest()


@dataclass
class ProvenanceChain:
    """Append-only, hash-chained AND optionally Ed25519-signed log for one deal."""

    deal_id: str
    receipts: list[dict] = field(default_factory=list)
    signing_key: Any = None          # Ed25519PrivateKey, or None to skip signing
    public_key: str = ""             # hex; derived from signing_key if signing

    def __post_init__(self) -> None:
        if self.signing_key is not None and not self.public_key:
            self.public_key = public_key_hex(self.signing_key)

    @property
    def head(self) -> str:
        return self.receipts[-1]["hash"] if self.receipts else GENESIS

    def append(self, kind: str, data: dict | None = None, *, actor: str | None = None) -> dict:
        """Append a step. Returns the receipt; signs the hash if a key is present."""
        seq = len(self.receipts)
        step = {"kind": kind, "actor": actor, "data": data or {}}
        h = _hash(self.head, seq, step)
        receipt = {"seq": seq, **step, "prev_hash": self.head, "hash": h}
        if self.signing_key is not None:
            receipt["sig"] = self.signing_key.sign(bytes.fromhex(h)).hex()
        self.receipts.append(receipt)
        return receipt

    def to_dict(self) -> dict:
        d = {"deal_id": self.deal_id, "genesis": GENESIS, "receipts": self.receipts}
        if self.public_key:
            d["public_key"] = self.public_key
        return d


def verify_chain(receipts: list[dict], *, owner_pubkey: Optional[str] = None) -> dict:
    """Re-attest a chain from receipts alone. Returns {ok, broken_at, reason}.

    If ``owner_pubkey`` (hex) is given, EVERY receipt must additionally carry a
    valid Ed25519 signature over its hash — so editing a step and recomputing the
    forward hashes is no longer enough; forgery requires the owner's private key.
    """
    from cryptography.exceptions import InvalidSignature

    pub = _load_pub(owner_pubkey) if owner_pubkey else None
    prev = GENESIS
    for i, r in enumerate(receipts):
        if r.get("seq") != i:
            return {"ok": False, "broken_at": i, "reason": f"seq mismatch at index {i}"}
        if r.get("prev_hash") != prev:
            return {"ok": False, "broken_at": i, "reason": f"prev_hash break at seq {i}"}
        step = {"kind": r.get("kind"), "actor": r.get("actor"), "data": r.get("data", {})}
        expect = _hash(prev, r["seq"], step)
        if r.get("hash") != expect:
            return {"ok": False, "broken_at": i, "reason": f"hash mismatch at seq {i} (tampered)"}
        if pub is not None:
            sig = r.get("sig")
            if not sig:
                return {"ok": False, "broken_at": i, "reason": f"missing signature at seq {i}"}
            try:
                pub.verify(bytes.fromhex(sig), bytes.fromhex(r["hash"]))
            except InvalidSignature:
                return {"ok": False, "broken_at": i, "reason": f"bad signature at seq {i} (forged)"}
        prev = r["hash"]
    suffix = " + signatures" if pub is not None else ""
    return {"ok": True, "broken_at": None, "reason": f"chain intact ({len(receipts)} links){suffix}"}
