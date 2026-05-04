"""Run a deterministic demo analysis without installing the package."""

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beleggingsraadgever.advisor import Advisor
from beleggingsraadgever.sample_data import seed_demo
from beleggingsraadgever.storage import SQLiteRepository


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "beleggingsraadgever-demo.sqlite"
        repository = SQLiteRepository(db_path)
        seed_demo(repository)
        advisor = Advisor(repository)
        print(advisor.render_markdown(advisor.analyze("DEMO")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
