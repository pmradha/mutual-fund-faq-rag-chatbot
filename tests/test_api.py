import http.client
import json
from pathlib import Path
import sys
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from api import create_server


class FakeAnswerService:
    def __init__(self, answer="Facts-only answer"):
        self.result = answer
        self.questions = []

    def answer(self, question):
        self.questions.append(question)
        return self.result


class AnswerApiTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeAnswerService()
        self.server = create_server(self.service, port=0)
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

    def request(self, path, payload):
        body = json.dumps(payload)
        self.connection.request(
            "POST", path, body=body, headers={"Content-Type": "application/json"}
        )
        response = self.connection.getresponse()
        return response.status, json.loads(response.read())

    def test_post_answer_returns_service_result_without_exposing_other_fields(self):
        status, payload = self.request(
            "/api/answer", {"question": "What is the minimum SIP?"}
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"answer": "Facts-only answer"})
        self.assertEqual(self.service.questions, ["What is the minimum SIP?"])

    def test_invalid_or_extra_request_fields_are_rejected(self):
        status, payload = self.request(
            "/api/answer", {"question": "What is the minimum SIP?", "email": "a@b.com"}
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload, {"error": "Invalid request"})
        self.assertEqual(self.service.questions, [])

    def test_unknown_path_is_not_served(self):
        status, payload = self.request("/other", {"question": "Question"})

        self.assertEqual(status, 404)
        self.assertEqual(payload, {"error": "Not found"})
        self.assertEqual(self.service.questions, [])


if __name__ == "__main__":
    unittest.main()