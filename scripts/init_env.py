"""Create local credentials without printing secrets or overwriting existing files."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / '.env'
if target.exists():
    print('.env already exists; left unchanged')
else:
    with target.open('x') as f:
        f.write(f'ADMIN_TOKEN={secrets.token_urlsafe(32)}\n')
        f.write(f'GATEWAY_TOKEN={secrets.token_urlsafe(32)}\n')
        f.write('REDIS_URL=redis://localhost:6379/0\nPROVIDER=mock\n')
    target.chmod(0o600)
    print('Created .env. Copy ADMIN_TOKEN into the local console; keep this file private.')
