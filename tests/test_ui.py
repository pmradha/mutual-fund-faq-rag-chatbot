import http.client
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ui_server import BACKEND_URL, create_server


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return b'{"answer":"Minimum SIP: INR 100."}'


class ChatUiTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(port=0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_address[1]
        )

    def tearDown(self):
        self.connection.close()
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def test_homepage_contains_required_facts_only_chat_content(self):
        self.connection.request("GET", "/")
        response = self.connection.getresponse()
        html = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Welcome.", html)
        self.assertIn("Facts-only. No investment advice.", html)
        self.assertEqual(html.count('class="example"'), 3)
        self.assertIn('id="question-form"', html)

    def test_static_javascript_and_stylesheet_are_served(self):
        for path, expected in (
            ("/app.js", 'fetch("/api/answer"'),
            ("/styles.css", "@media (max-width: 620px)"),
        ):
            with self.subTest(path=path):
                self.connection.request("GET", path)
                response = self.connection.getresponse()
                content = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn(expected, content)

    def test_answer_endpoint_proxies_json_to_existing_backend(self):
        payload = {"question": "What is the minimum SIP?"}
        body = json.dumps(payload)
        with patch("ui_server.urlopen", return_value=FakeResponse()) as backend:
            self.connection.request(
                "POST",
                "/api/answer",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = self.connection.getresponse()
            result = json.loads(response.read())

        self.assertEqual(response.status, 200)
        self.assertEqual(result["answer"], "Minimum SIP: INR 100.")
        backend.assert_called_once()
        request = backend.call_args.args[0]
        self.assertEqual(request.full_url, BACKEND_URL)
        self.assertEqual(json.loads(request.data), payload)


if __name__ == "__main__":
    unittest.main()