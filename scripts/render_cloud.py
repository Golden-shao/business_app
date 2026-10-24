"""Render a reviewed Kubernetes base with a real HTTPS entrypoint; never applies it."""
import argparse
import copy
import json
from pathlib import Path
import re
import subprocess

import yaml


def cloud_resources(base, domain, email, image, staging=False):
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+', domain):
        raise ValueError('Provide a DNS hostname without scheme, path or port')
    if domain == 'example.com' or domain.endswith(('.example.com', '.test', '.invalid', '.localhost', '.local')):
        raise ValueError('Replace the example domain with a domain you control')
    if not re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', email):
        raise ValueError('Provide a valid operator contact email')
    if not re.fullmatch(r'ghcr\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}', image):
        raise ValueError('Use a publicly pullable ghcr.io image pinned by sha256 digest')
    items = copy.deepcopy(base)
    gateway = next(r for r in items if r['kind'] == 'Deployment' and r['metadata']['name'] == 'gateway')
    container = gateway['spec']['template']['spec']['containers'][0]
    container['image'] = image
    container['env'] = [e for e in container['env'] if e['name'] not in ['CACHE_TTL_SECONDS', 'CORS_ORIGINS']]
    container['env'].extend([{'name': 'CACHE_TTL_SECONDS', 'value': '0'}, {'name': 'CORS_ORIGINS', 'value': '[]'}])
    issuer_name = 'harbor-staging' if staging else 'harbor-live'
    metadata = lambda name: {'name': name, 'namespace': 'harbor'}
    items.extend([
        {'apiVersion': 'cert-manager.io/v1', 'kind': 'ClusterIssuer', 'metadata': {'name': issuer_name},
         'spec': {'acme': {'email': email,
           'server': 'https://acme-staging-v02.api.letsencrypt.org/directory' if staging else 'https://acme-v02.api.letsencrypt.org/directory',
           'privateKeySecretRef': {'name': issuer_name + '-account'},
           'solvers': [{'http01': {'ingress': {'ingressClassName': 'traefik'}}}]}}},
        {'apiVersion': 'traefik.io/v1alpha1', 'kind': 'Middleware', 'metadata': metadata('https-redirect'),
         'spec': {'redirectScheme': {'scheme': 'https', 'permanent': True}}},
        {'apiVersion': 'networking.k8s.io/v1', 'kind': 'Ingress',
         'metadata': {**metadata('gateway-http'), 'annotations': {
             'traefik.ingress.kubernetes.io/router.entrypoints': 'web',
             'traefik.ingress.kubernetes.io/router.middlewares': 'harbor-https-redirect@kubernetescrd'}},
         'spec': {'ingressClassName': 'traefik', 'rules': [{'host': domain, 'http': {'paths': [
             {'path': '/', 'pathType': 'Prefix', 'backend': {'service': {'name': 'gateway', 'port': {'number': 8000}}}}]}}]}},
        {'apiVersion': 'networking.k8s.io/v1', 'kind': 'Ingress',
         'metadata': {**metadata('gateway-https'), 'annotations': {
             'traefik.ingress.kubernetes.io/router.entrypoints': 'websecure',
             'cert-manager.io/cluster-issuer': issuer_name}},
         'spec': {'ingressClassName': 'traefik', 'tls': [{'hosts': [domain], 'secretName': 'harbor-tls'}],
             'rules': [{'host': domain, 'http': {'paths': [{'path': '/', 'pathType': 'Prefix',
                 'backend': {'service': {'name': 'gateway', 'port': {'number': 8000}}}}]}}]}},
        {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': metadata('gateway-from-ingress'),
         'spec': {'podSelector': {'matchLabels': {'app': 'harbor-gateway'}}, 'policyTypes': ['Ingress'],
             'ingress': [{'from': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'kube-system'}},
                                   'podSelector': {'matchLabels': {'app.kubernetes.io/name': 'traefik'}}}],
                          'ports': [{'protocol': 'TCP', 'port': 8000}]}]}}
    ])
    return items


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain', required=True)
    parser.add_argument('--email', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--staging', action='store_true', help='Use untrusted ACME staging certificates during DNS tests')
    parser.add_argument('--kubectl', default='kubectl')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    base = list(yaml.safe_load_all(subprocess.check_output([args.kubectl, 'kustomize', str(root / 'deploy/k8s')], text=True)))
    try:
        items = cloud_resources(base, args.domain, args.email, args.image, args.staging)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': items}, indent=2))


if __name__ == '__main__':
    main()
