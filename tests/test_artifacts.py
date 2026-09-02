import unittest
from pathlib import Path

from proofside.artifacts import accepted_contract_path, candidate_contract_path


class ArtifactPathTests(unittest.TestCase):
    def test_derives_source_adjacent_contract_paths(self) -> None:
        source_path = Path("research", "budget.py")

        self.assertEqual(
            candidate_contract_path(source_path, "remaining"),
            Path("research", ".proofside", "budget.remaining.candidate.json"),
        )
        self.assertEqual(
            accepted_contract_path(source_path, "remaining"),
            Path("research", ".proofside", "budget.remaining.contract.json"),
        )


if __name__ == "__main__":
    unittest.main()
