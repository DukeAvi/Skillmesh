import io
import json
from unittest.mock import MagicMock, patch

from web import app


def post_admin(role, csrf=True):
    handler = object.__new__(app.Handler)
    handler.path = "/api/admin/users"
    body = json.dumps({"name": "New User", "email": "new@example.com", "password": "Example123", "role": "admin"}).encode()
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    handler.send_json = MagicMock()
    handler._require_csrf = MagicMock(return_value=csrf)
    handler.session = MagicMock(return_value={"user_id": 1})
    with patch.object(app, "query", return_value=[{"role": role}]), patch.object(app, "pg_connect") as connect:
        cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (42,)
        handler.do_POST()
    return handler, connect


def test_admin_can_create_account():
    handler, connect = post_admin("admin")
    assert handler.send_json.call_args.args[1] == 201
    assert connect.called


def test_non_admin_cannot_create_account():
    handler, connect = post_admin("student")
    assert handler.send_json.call_args.args[1] == 403
    assert not connect.called


def test_missing_csrf_prevents_creation():
    handler, connect = post_admin("admin", csrf=False)
    assert not handler.send_json.called
    assert not connect.called


def post_setup(code, existing_admin=False, csrf=True):
    handler = object.__new__(app.Handler)
    handler.path = "/api/admin/setup"
    body = json.dumps({"code": code}).encode()
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    handler.send_json = MagicMock()
    handler._require_csrf = MagicMock(return_value=csrf)
    handler.session = MagicMock(return_value={"user_id": 1})
    with patch.dict(app.os.environ, {"SKILLMESH_SETUP_CODE": "a-private-code-123"}), \
         patch.object(app, "_check_rate_limit", return_value=True), \
         patch.object(app, "pg_connect") as connect:
        cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [(1,) if existing_admin else None, (1,)]
        handler.do_POST()
    return handler, connect


def test_first_admin_setup():
    handler, connect = post_setup("a-private-code-123")
    assert handler.send_json.call_args.args[0] == {"ok": True}
    assert connect.called


def test_setup_rejects_wrong_code():
    handler, connect = post_setup("wrong")
    assert handler.send_json.call_args.args[1] == 403
    assert not connect.called


def test_setup_rejects_existing_admin():
    handler, _ = post_setup("a-private-code-123", existing_admin=True)
    assert handler.send_json.call_args.args[1] == 409


def test_setup_requires_csrf():
    handler, connect = post_setup("a-private-code-123", csrf=False)
    assert not handler.send_json.called
    assert not connect.called
