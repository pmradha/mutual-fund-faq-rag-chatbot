import http.client
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from answer import AnswerService
from api import create_server as create_answer_server
from test_answer_service import FakeGroqClient, FakeRetriever, SOURCE_URL, evidence
from ui_server import create_server as create_ui_server


class PhaseFiveAcceptanceTests(unittest.TestCase):
    def test_chat_request_traverses_ui_proxy_api_and_answer_service(self):
        retriever = FakeRetriever([evidence()])
        client = FakeGroqClient()
        answer_service = AnswerService(client=client, retriever=retriever)
        api_server = create_answer_server(answer_service, port=0)
        api_thread = threading.Thread(target=api_server.serve_forever)
        api_thread.start()
        ui_server = create_ui_server(port=0)
        ui_thread = threading.Thread(target=ui_server.serve_forever)
        ui_thread.start()

        question = "What is the minimum SIP?"
        backend_url = (
            f"http://127.0.0.1:{api_server.server_address[1]}/api/answer"
        )
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", ui_server.server_address[1]
            )
            with patch("ui_server.BACKEND_URL", backend_url):
                connection.request(
                    "POST",
                    "/api/answer",
                    body=json.dumps({"question": question}),
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                result = json.loads(response.read())
            connection.close()
        finally:
            ui_server.shutdown()
            ui_thread.join()
            ui_server.server_close()
            api_server.shutdown()
            api_thread.join()
            api_server.server_close()

        self.assertEqual(response.status, 200)
        self.assertIn("INR 100", result["answer"])
        self.assertIn(f"]({SOURCE_URL})", result["answer"])
        self.assertIn("Last updated from sources: 2026-08", result["answer"])
        self.assertEqual([call[0] for call in retriever.calls], [question])
        self.assertEqual(len(client.completions.calls), 1)


if __name__ == "__main__":
    unittest.main()