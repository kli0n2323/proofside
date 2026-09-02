from pathlib import Path


def candidate_contract_path(file_path: Path, function_name: str) -> Path:
    return file_path.parent / ".proofside" / f"{file_path.stem}.{function_name}.candidate.json"


def accepted_contract_path(file_path: Path, function_name: str) -> Path:
    return file_path.parent / ".proofside" / f"{file_path.stem}.{function_name}.contract.json"
