import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from answer import (
    ADVICE_REFUSAL,
    NOT_FOUND_RESPONSE,
    PII_REFUSAL,
    AnswerService,
    AnswerServiceConfigurationError,
)
from safety import RequestIntent, classify_request, contains_pii


SOURCE_URL = "https://www.hdfcfund.com/explore/mutual-funds/hdfc-large-cap-fund/regular"
SECOND_SOURCE_URL = "https://www.hdfcfund.com/explore/mutual-funds/hdfc-flexi-cap-fund/direct"


def evidence(text="Minimum SIP: INR 100.", source_url=SOURCE_URL):
    return {
        "chunk_id": "source-1-test",
        "text": text,
        "distance": 0.2,
        "metadata": {
            "chunk_id": "source-1-test",
            "source_id": "1",
            "source_url": source_url,
            "source_title": "HDFC Large Cap Fund",
            "source_type": "Scheme page",
            "publisher": "HDFC Mutual Fund",
            "scheme_or_scope": "HDFC Large Cap Fund",
            "section_path": "Scheme facts",
            "fetched_at": "2026-09-29T08:00:00+00:00",
            "document_date": "2026-08",
            "content_hash": "a" * 64,
            "chunk_index": 0,
        },
    }


class FakeRetriever:
    def __init__(self, matches=None):
        self.matches = [evidence()] if matches is None else matches
        self.calls = []

    def __call__(self, question, **kwargs):
        self.calls.append((question, kwargs))
        return self.matches


class FakeCompletions:
    def __init__(self, response="The minimum SIP is INR 100."):
        self.responses = list(response) if isinstance(response, (list, tuple)) else [response]
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response_index = min(len(self.calls) - 1, len(self.responses) - 1)
        message = type("Message", (), {"content": self.responses[response_index]})()
        choice = type("Choice", (), {"message": message})()
        return type("Completion", (), {"choices": [choice]})()


class FakeGroqClient:
    def __init__(self, response="The minimum SIP is INR 100."):
        self.completions = FakeCompletions(response)
        self.chat = type("Chat", (), {"completions": self.completions})()


class AnswerServiceTests(unittest.TestCase):
    def make_service(self, response="The minimum SIP is INR 100.", matches=None):
        self.retriever = FakeRetriever(matches)
        self.client = FakeGroqClient(response)
        self.service = AnswerService(client=self.client, retriever=self.retriever)
        return self.service

    def test_normal_factual_faq_uses_only_retrieved_evidence(self):
        service = self.make_service()

        result = service.answer("What is the minimum SIP for HDFC Large Cap Fund?")

        self.assertIn("INR 100", result)
        sent_context = self.client.completions.calls[0]["messages"][1]["content"]
        self.assertIn("retrieved_evidence", sent_context)
        self.assertIn("Minimum SIP: INR 100.", sent_context)
        self.assertEqual(self.client.completions.calls[0]["model"], "qwen/qwen3.8-27b")
        self.assertEqual(len(self.retriever.calls), 1)

    def test_generation_uses_one_source_group_and_cites_the_supporting_group(self):
        matches = [
            evidence("Exit load: 1%.", SOURCE_URL),
            evidence("Minimum SIP: INR 100.", SECOND_SOURCE_URL),
        ]
        service = self.make_service(["NOT_SUPPORTED", "The minimum SIP is INR 100."], matches)

        result = service.answer("What is the minimum SIP?")

        self.assertIn(f"]({SECOND_SOURCE_URL})", result)
        self.assertNotIn(f"]({SOURCE_URL})", result)
        first_context = self.client.completions.calls[0]["messages"][1]["content"]
        second_context = self.client.completions.calls[1]["messages"][1]["content"]
        self.assertIn("Exit load: 1%.", first_context)
        self.assertNotIn("Minimum SIP: INR 100.", first_context)
        self.assertIn("Minimum SIP: INR 100.", second_context)
        self.assertNotIn("Exit load: 1%.", second_context)

    def test_all_source_groups_unsupported_returns_not_found(self):
        matches = [
            evidence("Exit load: 1%.", SOURCE_URL),
            evidence("Riskometer: Very High.", SECOND_SOURCE_URL),
        ]
        service = self.make_service(["NOT_SUPPORTED", "NOT_SUPPORTED"], matches)

        self.assertEqual(service.answer("What is the minimum SIP?"), NOT_FOUND_RESPONSE)
        self.assertEqual(len(self.client.completions.calls), 2)

    def test_insufficient_evidence_does_not_call_groq(self):
        service = self.make_service(matches=[])

        result = service.answer("What is the current expense ratio?")

        self.assertEqual(result, NOT_FOUND_RESPONSE)
        self.assertEqual(self.client.completions.calls, [])

    def test_pii_rejected_before_retrieval_or_generation(self):
        sensitive_questions = (
            "My PAN is ABCDE1234F",
            "Aadhaar number 1234 5678 9012",
            "Bank account number: 123456789012",
            "OTP: 482019",
            "Email me at person@example.com",
            "Call me at +91 9876543210",
        )
        for question in sensitive_questions:
            with self.subTest(question=question):
                service = self.make_service()
                self.assertTrue(contains_pii(question))
                self.assertEqual(service.answer(question), PII_REFUSAL)
                self.assertEqual(self.retriever.calls, [])
                self.assertEqual(self.client.completions.calls, [])

    def test_advice_and_opinion_requests_are_refused_without_groq(self):
        service = self.make_service()

        result = service.answer("Should I buy HDFC Large Cap Fund?")

        self.assertIn(ADVICE_REFUSAL, result)
        self.assertIn(f"]({SOURCE_URL})", result)
        self.assertEqual(self.client.completions.calls, [])
        self.assertEqual(classify_request("Which fund should I choose?"), RequestIntent.ADVICE)
        self.assertEqual(
            classify_request("Can you compare the expected returns?"),
            RequestIntent.PERFORMANCE,
        )

    def test_paraphrased_advice_is_refused_but_factual_portfolio_faq_is_allowed(self):
        advice_questions = (
            "Is this fund right for my goals?",
            "Would this scheme suit my risk profile?",
            "How should I allocate my portfolio?",
            "What percentage of my portfolio should go into equity funds?",
            "How should I divide my money across these schemes?",
        )
        for question in advice_questions:
            with self.subTest(question=question):
                service = self.make_service()
                self.assertEqual(classify_request(question), RequestIntent.ADVICE)
                self.assertIn(ADVICE_REFUSAL, service.answer(question))
                self.assertEqual(self.client.completions.calls, [])

        self.assertEqual(
            classify_request("What is the current portfolio allocation of this fund?"),
            RequestIntent.FACTUAL,
        )

    def test_paraphrased_performance_requests_are_refused(self):
        questions = (
            "How did this fund do last year?",
            "How much could I earn from this scheme?",
        )
        for question in questions:
            with self.subTest(question=question):
                service = self.make_service()
                self.assertEqual(classify_request(question), RequestIntent.PERFORMANCE)
                self.assertIn("performance", service.answer(question).lower())
                self.assertEqual(self.client.completions.calls, [])

    def test_factual_answer_has_exactly_one_official_source_link_and_freshness(self):
        service = self.make_service()

        result = service.answer("What is the minimum SIP?")

        self.assertEqual(result.count("https://"), 1)
        self.assertIn(f"[Official source]({SOURCE_URL})", result)
        self.assertIn("Last updated from sources: 2026-08", result)

    def test_overlong_generated_response_is_not_returned_as_factual(self):
        service = self.make_service("First. Second. Third. Fourth.")

        result = service.answer("What is the minimum SIP?")

        self.assertIn(NOT_FOUND_RESPONSE, result)
        self.assertNotIn("First. Second. Third.", result)

    def test_generated_opinion_or_link_is_discarded(self):
        for unsafe_response in (
            "You should buy this fund.",
            "Visit https://unapproved.example for details.",
            "This fund is right for your goals.",
            "It grew 12% last year.",
            "Put 40% of your portfolio in this scheme.",
        ):
            with self.subTest(response=unsafe_response):
                service = self.make_service(unsafe_response)
                self.assertIn(NOT_FOUND_RESPONSE, service.answer("What is the minimum SIP?"))

    def test_api_key_is_loaded_server_side_and_never_sent_in_prompt_or_answer(self):
        secret = "groq-test-secret-not-for-prompts"
        client = FakeGroqClient()
        retriever = FakeRetriever()
        with patch.dict(os.environ, {"GROQ_API_KEY": secret}):
            with patch("answer.Groq", return_value=client) as groq_factory:
                service = AnswerService(retriever=retriever)
                result = service.answer("What is the minimum SIP?")

        groq_factory.assert_called_once_with(api_key=secret)
        request = client.completions.calls[0]
        self.assertNotIn(secret, json.dumps(request["messages"]))
        self.assertNotIn(secret, result)

    def test_missing_api_key_fails_without_exposing_secret(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AnswerServiceConfigurationError) as error:
                AnswerService()
        self.assertNotIn("secret", str(error.exception).lower())


if __name__ == "__main__":
    unittest.main()