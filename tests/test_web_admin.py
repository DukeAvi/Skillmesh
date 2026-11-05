import io
import json
from unittest.mock import MagicMock, patch

from web import app


def setup_request(code, password="Example123", activated=False):
    handler = object.__new__(app.Handler)
    handler.path = "/api/moderator/setup"
    body = json.dumps({"code": code, "password": password}).encode()
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    handler.send_json = MagicMock()
    with patch.dict(app.os.environ, {"SKILLMESH_SETUP_CODE": "a-private-code-123"}), \
         patch.object(app, "_check_rate_limit", return_value=True), \
         patch.object(app, "pg_connect") as connect:
        cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None if activated else (1,)
        handler.do_POST()
    return handler, connect


def test_setup_activates_seeded_moderator():
    handler, connect = setup_request("a-private-code-123")
    assert handler.send_json.call_args.args[0] == {"ok": True}
    cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    assert cursor.execute.call_args.args[1][1:] == ("arjun@campus.edu", "placeholder-hash-arjun")


def test_setup_rejects_wrong_code():
    handler, connect = setup_request("wrong")
    assert handler.send_json.call_args.args[1] == 403
    assert not connect.called


def test_setup_cannot_replace_an_existing_password():
    handler, _ = setup_request("a-private-code-123", activated=True)
    assert handler.send_json.call_args.args[1] == 409


def test_setup_rejects_weak_password():
    handler, connect = setup_request("a-private-code-123", password="short")
    assert handler.send_json.call_args.args[1] == 400
    assert not connect.called
