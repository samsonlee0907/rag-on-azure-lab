from __future__ import annotations

import unittest

from backend.services.indexing import AzureSearchKnowledgeBaseAdapter


class DirectSearchBodyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = AzureSearchKnowledgeBaseAdapter()

    def test_build_full_text_body_uses_search_without_vector_queries(self) -> None:
        body = self.adapter._build_direct_search_body(
            question="find the workflow",
            retrieval_mode="full_text",
            filter_expression="doc_id eq 'abc'",
            query_vector=None,
        )

        self.assertEqual(body["search"], "find the workflow")
        self.assertEqual(body["filter"], "doc_id eq 'abc'")
        self.assertNotIn("vectorQueries", body)
        self.assertNotIn("captions", body)

    def test_build_vector_body_uses_star_and_vector_queries(self) -> None:
        body = self.adapter._build_direct_search_body(
            question="find the workflow",
            retrieval_mode="vector",
            filter_expression="",
            query_vector=[0.1, 0.2, 0.3],
        )

        self.assertEqual(body["search"], "*")
        self.assertEqual(body["vectorQueries"][0]["kind"], "vector")
        self.assertEqual(body["vectorQueries"][0]["vector"], [0.1, 0.2, 0.3])
        self.assertNotIn("captions", body)

    def test_build_hybrid_body_uses_search_and_vector_queries(self) -> None:
        body = self.adapter._build_direct_search_body(
            question="find the workflow",
            retrieval_mode="hybrid",
            filter_expression="",
            query_vector=[0.1, 0.2, 0.3],
        )

        self.assertEqual(body["search"], "find the workflow")
        self.assertEqual(body["vectorQueries"][0]["kind"], "vector")
        self.assertEqual(body["vectorQueries"][0]["vector"], [0.1, 0.2, 0.3])
        self.assertNotIn("captions", body)


if __name__ == "__main__":
    unittest.main()
