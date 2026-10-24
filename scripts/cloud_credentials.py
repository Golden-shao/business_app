"""Initialize per-instance credentials on the VM; never emit token values."""
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess


def ensure_credentials(path):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.exists():
        # Exclusive create prevents concurrent bootstraps from silently rotating tokens.
        with open(path, 'x', opener=lambda name, flags: os.open(name, flags, 0o600)) as file:
            file.write(f'ADMIN_TOKEN={secrets.token_urlsafe(32)}\nGATEWAY_TOKEN={secrets.token_urlsafe(32)}\n')
    path.chmod(0o600)
    values = dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)
    if any(len(values.get(key, '')) < 16 for key in ['ADMIN_TOKEN', 'GATEWAY_TOKEN']) or values['ADMIN_TOKEN'] == values['GATEWAY_TOKEN']:
        raise ValueError('Existing instance credentials are invalid; inspect the protected file locally')
    return {key: values[key] for key in ['ADMIN_TOKEN', 'GATEWAY_TOKEN']}


def main():
    path = Path('/etc/harbor/access.env')
    credentials = ensure_credentials(path)
    secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'harbor-auth', 'namespace': 'harbor'},
              'type': 'Opaque', 'data': {k: base64.b64encode(v.encode()).decode() for k, v in credentials.items()}}
    subprocess.run(['kubectl', 'apply', '--server-side', '--field-manager=harbor-bootstrap', '-f', '-'],
                   input=json.dumps(secret), text=True, check=True)
    print(f'Instance credentials stored in {path}; read them only through your authenticated SSM session.')


if __name__ == '__main__':
    main()
