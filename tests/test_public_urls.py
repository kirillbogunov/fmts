import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starlette.requests import Request
from app.config import Settings
from app.services.urls import resolve_public_base_url, public_url


def make_request(host='localhost:8000', scheme='http', forwarded_proto=None, forwarded_host=None):
    headers=[(b'host', host.encode())]
    if forwarded_proto:
        headers.append((b'x-forwarded-proto', forwarded_proto.encode()))
    if forwarded_host:
        headers.append((b'x-forwarded-host', forwarded_host.encode()))
    scope={
        'type':'http', 'http_version':'1.1', 'method':'GET', 'scheme':scheme,
        'path':'/equipment/1/qr.png', 'raw_path':b'/equipment/1/qr.png',
        'query_string':b'', 'headers':headers, 'server':('localhost',8000), 'client':('127.0.0.1',12345)
    }
    return Request(scope)


def test_public_base_url_setting_wins(monkeypatch):
    monkeypatch.delenv('RENDER_EXTERNAL_URL', raising=False)
    s=Settings(_env_file=None, public_base_url='https://fmts-demo.onrender.com', base_url='')
    req=make_request()
    assert resolve_public_base_url(req,s) == 'https://fmts-demo.onrender.com'
    assert public_url(req,s,'/scan/abc') == 'https://fmts-demo.onrender.com/scan/abc'


def test_render_external_url_fallback(monkeypatch):
    monkeypatch.setenv('RENDER_EXTERNAL_URL','https://auto-fmts.onrender.com')
    s=Settings(_env_file=None, public_base_url='', base_url='')
    assert resolve_public_base_url(make_request(),s) == 'https://auto-fmts.onrender.com'


def test_proxy_headers_fallback(monkeypatch):
    monkeypatch.delenv('RENDER_EXTERNAL_URL', raising=False)
    s=Settings(_env_file=None, public_base_url='', base_url='')
    req=make_request(forwarded_proto='https', forwarded_host='fmts.example.kz')
    assert resolve_public_base_url(req,s) == 'https://fmts.example.kz'


def test_local_request_fallback(monkeypatch):
    monkeypatch.delenv('RENDER_EXTERNAL_URL', raising=False)
    s=Settings(_env_file=None, public_base_url='', base_url='')
    assert resolve_public_base_url(make_request(),s) == 'http://localhost:8000'
