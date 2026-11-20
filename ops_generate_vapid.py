"""Create the Web Push (VAPID) key pair for the portal. Offline: it only writes two files under private/.

    .venv/bin/python ops_generate_vapid.py

Prints the PUBLIC key and the file names only; the private key is never printed. Store the files in Secret Manager
(see RUNBOOK.md, "Chat and push notifications"). Refuses to overwrite existing files so a live key is not rotated by accident.
"""
import base64
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

PRIVATE = Path('private/vapid-private.txt')
PUBLIC = Path('private/vapid-public.txt')


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def generate():
    key = ec.generate_private_key(ec.SECP256R1())
    private = b64(key.private_numbers().private_value.to_bytes(32, 'big'))
    public = b64(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    return private, public


def main():
    if PRIVATE.exists() or PUBLIC.exists():
        print('private/vapid-*.txt already exist; refusing to overwrite (rotating the key drops every saved subscription).')
        return 1
    PRIVATE.parent.mkdir(mode=0o700, exist_ok=True)
    private, public = generate()
    for path, value in ((PRIVATE, private), (PUBLIC, public)):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(value)
    print('public key :', public)
    print('written    :', PRIVATE, '(secret)', PUBLIC)
    return 0


if __name__ == '__main__':
    sys.exit(main())
