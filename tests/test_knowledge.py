from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.knowledge import HashingVectorizer, chunk_text, cosine_similarity
from beleggingsraadgever.storage import SQLiteRepository


class KnowledgeTests(unittest.TestCase):
    def test_chunk_text_creates_chunks(self) -> None:
        chunks = chunk_text("Een zin. " * 300, document_id=1, max_chars=200, overlap=20)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_index, 0)

    def test_vectorizer_similarity(self) -> None:
        vectorizer = HashingVectorizer(dimensions=64)
        left = vectorizer.vectorize("vrije kasstroom dividend schuld")
        right = vectorizer.vectorize("dividend en vrije kasstroom")
        unrelated = vectorizer.vectorize("consumentenvertrouwen inflatie rente")
        self.assertGreater(cosine_similarity(left, right), cosine_similarity(left, unrelated))

    def test_repository_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite", HashingVectorizer(dimensions=64))
            repo.init()
            repo.add_document(
                title="Dividend test",
                source_type="test",
                raw_text="Dividend moet worden ondersteund door vrije kasstroom en lage schuld.",
            )
            hits = repo.search_knowledge("vrije kasstroom dividend", limit=1)
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].title, "Dividend test")

    def test_document_import_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = SQLiteRepository(Path(tmp) / "test.sqlite", HashingVectorizer(dimensions=64))
            repo.init()
            first = repo.add_document(
                title="Idempotent",
                source_type="test",
                raw_text="Een document over waardering en marges.",
            )
            second = repo.add_document(
                title="Idempotent",
                source_type="test",
                raw_text="Een document over waardering en marges.",
            )
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
