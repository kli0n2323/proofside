from nagini_contracts.contracts import Ensures, Result


async def allocate_remaining(total_shots: int, first_bucket: int) -> int:
    Ensures(Result() >= 0)
    return total_shots - first_bucket

