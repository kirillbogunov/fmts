"""Generate Render-friendly VAPID keys for FMTS Web Push.

Run once locally and copy the printed values to Render Environment.
Never commit the private key to git.
"""
from __future__ import annotations
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

private = ec.generate_private_key(ec.SECP256R1())
private_pem = private.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
public_raw = private.public_key().public_bytes(
    serialization.Encoding.X962,
    serialization.PublicFormat.UncompressedPoint,
)
public_b64 = base64.urlsafe_b64encode(public_raw).rstrip(b'=').decode('ascii')
private_b64 = base64.b64encode(private_pem).decode('ascii')
print('PUSH_VAPID_PUBLIC_KEY=' + public_b64)
print('PUSH_VAPID_PRIVATE_KEY=base64:' + private_b64)
print('PUSH_VAPID_SUBJECT=mailto:admin@example.com')
