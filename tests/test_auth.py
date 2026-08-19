import unittest

from fastapi.testclient import TestClient
from serial_bridge.auth import McpBearerAuth, _send_authorized, _who_for
from serial_bridge.token_store import reset_token_store
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route


class UninitializedTokenStoreAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_token_store()

    def tearDown(self) -> None:
        reset_token_store()

    def test_bearer_checks_fail_closed_when_store_is_uninitialized(self) -> None:
        self.assertFalse(_send_authorized("192.0.2.10", "Bearer secret"))
        self.assertEqual("user", _who_for("Bearer secret"))

        async def authorized_endpoint(request):
            return JSONResponse({"ok": True})

        app = McpBearerAuth(
            Starlette(routes=[Route("/", authorized_endpoint, methods=["GET"])])
        )
        response = TestClient(app).get(
            "/",
            headers={"Authorization": "Bearer secret"},
        )

        self.assertEqual(401, response.status_code)
        self.assertEqual("Bearer", response.headers["www-authenticate"])


if __name__ == "__main__":
    unittest.main()
