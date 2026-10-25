import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render = load_script('render_cloud')
credentials = load_script('cloud_credentials')
IMAGE = 'ghcr.io/golden-shao/modeljetty/gateway@sha256:' + 'a' * 64


def base():
    resources = []
    for name in ['namespace.yaml', 'redis.yaml', 'gateway.yaml', 'network-policy.yaml']:
        resources.extend(yaml.safe_load_all((ROOT / 'deploy/k8s' / name).read_text()))
    return resources


def test_cloud_routes_tls_and_keeps_internal_service_private():
    original = base()
    items = render.cloud_resources(original, 'gateway.harbor-demo.org', 'ops@harbor-demo.org', IMAGE)
    ingress = [r for r in items if r['kind'] == 'Ingress']
    assert len(ingress) == 2
    tls = next(r for r in ingress if r['metadata']['name'] == 'gateway-https')
    assert tls['spec']['tls'][0]['hosts'] == ['gateway.harbor-demo.org']
    assert tls['spec']['rules'][0]['http']['paths'][0]['backend']['service']['port']['number'] == 8000
    assert all(r['spec'].get('type', 'ClusterIP') == 'ClusterIP' for r in items if r['kind'] == 'Service')
    container = next(r for r in items if r['kind'] == 'Deployment')['spec']['template']['spec']['containers'][0]
    assert container['image'] == IMAGE
    assert {'name': 'CACHE_TTL_SECONDS', 'value': '0'} in container['env']
    assert next(r for r in original if r['kind'] == 'Deployment')['spec']['template']['spec']['containers'][0]['image'] == 'harbor-gateway:local'
    assert any(r['kind'] == 'NetworkPolicy' and r['metadata']['name'] == 'gateway-from-ingress' for r in items)


@pytest.mark.parametrize('domain,email,image', [
    ('gateway.example.com', 'ops@harbor-demo.org', IMAGE),
    ('https://gateway.harbor-demo.org:8080', 'ops@harbor-demo.org', IMAGE),
    ('gateway.harbor-demo.org', "ops';echo@harbor-demo.org", IMAGE),
    ('gateway.harbor-demo.org', 'ops@harbor-demo.org', 'ghcr.io/example/image:latest'),
])
def test_cloud_rejects_placeholder_and_unsafe_inputs(domain, email, image):
    with pytest.raises(ValueError):
        render.cloud_resources(base(), domain, email, image)


def test_acme_staging_is_an_explicit_untrusted_test_option():
    items = render.cloud_resources(base(), 'gateway.harbor-demo.org', 'ops@harbor-demo.org', IMAGE, staging=True)
    issuer = next(r for r in items if r['kind'] == 'ClusterIssuer')
    assert 'staging' in issuer['spec']['acme']['server']
    assert issuer['metadata']['name'] == 'harbor-staging'


def test_instance_credentials_are_private_and_not_rotated_on_rerun(tmp_path):
    path = tmp_path / 'private' / 'access.env'
    first = credentials.ensure_credentials(path)
    second = credentials.ensure_credentials(path)
    assert first == second
    assert first['ADMIN_TOKEN'] != first['GATEWAY_TOKEN']
    assert path.stat().st_mode & 0o777 == 0o600


def test_workflow_documents_parse_before_upload_to_github():
    for path in (ROOT / '.github/workflows').glob('*.yaml'):
        document = yaml.safe_load(path.read_text())
        assert isinstance(document.get('jobs'), dict), path.name
