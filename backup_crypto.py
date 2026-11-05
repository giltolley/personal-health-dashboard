"""Libsodium sealed-box encryption. Only the public key belongs on the runner."""
import base64
import os
from pathlib import Path
from nacl.public import PrivateKey,PublicKey,SealedBox

MAGIC=b'PHD-BACKUP-SEALED-V1\n'


def generate_keys():
    private=PrivateKey.generate()
    return (base64.b64encode(bytes(private)).decode(),
            base64.b64encode(bytes(private.public_key)).decode())


def encrypt(data,public_key):
    key=PublicKey(base64.b64decode(public_key.strip(),validate=True))
    return MAGIC+SealedBox(key).encrypt(data)


def decrypt(data,private_key):
    if not data.startswith(MAGIC):
        raise ValueError('Unsupported encrypted backup format.')
    key=PrivateKey(base64.b64decode(private_key.strip(),validate=True))
    return SealedBox(key).decrypt(data[len(MAGIC):])


def private_write(path,data):
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as stream:
        stream.write(data)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Decrypt a backup locally; never upload the private key.')
    parser.add_argument('--input',required=True)
    parser.add_argument('--private-key',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    clear=decrypt(Path(args.input).read_bytes(),Path(args.private_key).read_text())
    private_write(args.output,clear)
    print('Decrypted backup saved. Verify with backup_data.py restore-sqlite.')
