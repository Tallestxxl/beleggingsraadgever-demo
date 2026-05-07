from pathlib import Path
import os
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.document_text import _tool_env, _tool_path


class DocumentTextTests(unittest.TestCase):
    def test_tool_env_adds_tool_bin_and_tessdata_prefix(self) -> None:
        old_tessdata_prefix = os.environ.get("TESSDATA_PREFIX")
        try:
            os.environ.pop("TESSDATA_PREFIX", None)
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tool_path = root / "bin" / "tesseract"
                tessdata_path = root / "share" / "tessdata"
                tool_path.parent.mkdir()
                tessdata_path.mkdir(parents=True)
                tool_path.write_text("#!/bin/sh\n", encoding="utf-8")
                (tessdata_path / "eng.traineddata").write_text("fake", encoding="utf-8")

                env = _tool_env(str(tool_path))

                self.assertTrue(env["PATH"].startswith(str(tool_path.parent)))
                self.assertEqual(env["TESSDATA_PREFIX"], str(tessdata_path))
        finally:
            if old_tessdata_prefix is None:
                os.environ.pop("TESSDATA_PREFIX", None)
            else:
                os.environ["TESSDATA_PREFIX"] = old_tessdata_prefix

    def test_tool_path_uses_environment_override(self) -> None:
        old_override = os.environ.get("BELEGGINGSRAADGEVER_TESSERACT")
        try:
            os.environ["BELEGGINGSRAADGEVER_TESSERACT"] = "/tmp/custom-tesseract"
            self.assertEqual(_tool_path("tesseract", "BELEGGINGSRAADGEVER_TESSERACT"), "/tmp/custom-tesseract")
        finally:
            if old_override is None:
                os.environ.pop("BELEGGINGSRAADGEVER_TESSERACT", None)
            else:
                os.environ["BELEGGINGSRAADGEVER_TESSERACT"] = old_override


if __name__ == "__main__":
    unittest.main()
