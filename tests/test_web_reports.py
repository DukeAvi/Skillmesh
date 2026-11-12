import io
import json
from unittest.mock import MagicMock, patch

from web import app


def handler_for(path, payload):
    handler = object.__new__(app.Handler)
    handler.path = path
    body = json.dumps(payload).encode()
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    handler.send_json = MagicMock()
    handler._require_csrf = MagicMock(return_value=True)
    handler.session = MagicMock(return_value={"user_id": 1, "email": "user@example.com", "role": "student"})
    return handler


def test_user_can_report_another_user():
    handler = handler_for("/api/reports", {"user_id": 2, "reason": "Harassment"})
    with patch.object(app.moderation, "pg_connect") as connect:
        cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (7,)
        handler.do_POST()
    assert handler.send_json.call_args.args[1] == 201
    assert cursor.execute.call_args.args[1] == (1, "Harassment", 2)


def test_self_report_is_rejected():
    handler = handler_for("/api/reports", {"user_id": 1, "reason": "Test"})
    handler.do_POST()
    assert handler.send_json.call_args.args[1] == 400


def test_non_admin_cannot_ban():
    handler = handler_for("/api/moderation", {"action": "ban-user", "user_id": 2})
    handler.do_POST()
    assert handler.send_json.call_args.args[1] == 403


def test_moderator_can_ban_and_unban():
    for action in ("ban-user", "unban-user"):
        handler = handler_for("/api/moderation", {"action": action, "user_id": 2})
        handler.session.return_value = {"user_id": 1, "email": "arjun@campus.edu", "role": "admin"}
        with patch.object(app.moderation, "pg_connect") as connect:
            connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value.rowcount = 1
            handler.do_POST()
        cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        assert cursor.execute.called
        assert handler.send_json.call_args.args[0] == {"ok": True}


def test_banned_user_session_is_destroyed():
    handler = object.__new__(app.Handler)
    handler._get_session_token = MagicMock(return_value="token")
    with patch.object(app.auth, "_get_session", return_value={"user": {"user_id": 2}}), \
         patch.object(app, "query", return_value=[]), \
         patch.object(app.auth, "_destroy_session") as destroy:
        assert handler.session() is None
        destroy.assert_called_once_with("token")


def test_name_does_not_grant_moderator_access():
    assert not app.moderation.is_moderator({"name": "Arjun", "email": "other@example.com", "role": "admin"})
