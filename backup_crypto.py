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


def save_key_pair(directory):
    root=Path(directory)
    root.mkdir(parents=True,mode=0o700,exist_ok=False)
    private,public=generate_keys()
    private_write(root/'Health_Dashboard_Backup_Private_Key.txt',(private+'\n').encode())
    private_write(root/'Health_Dashboard_Backup_Public_Key.txt',(public+'\n').encode())
    return public


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Generate backup keys or decrypt a backup locally.')
    parser.add_argument('--generate-keys',metavar='NEW_DIRECTORY')
    parser.add_argument('--input')
    parser.add_argument('--private-key')
    parser.add_argument('--output')
    args=parser.parse_args()
    if args.generate_keys:
        if any([args.input,args.private_key,args.output]):
            parser.error('Key generation cannot be combined with decryption.')
        save_key_pair(args.generate_keys)
        print('Key pair saved. Keep the private key out of GitHub; add only the public key to BACKUP_PUBLIC_KEY.')
    else:
        if not all([args.input,args.private_key,args.output]):
            parser.error('Decryption requires --input, --private-key and --output.')
        clear=decrypt(Path(args.input).read_bytes(),Path(args.private_key).read_text())
        private_write(args.output,clear)
        print('Decrypted backup saved. Verify with backup_data.py restore-sqlite.')
