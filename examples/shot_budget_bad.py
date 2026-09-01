from nagini_contracts.contracts import Ensures, Requires, Result


def allocate_remaining(total_shots: int, first_bucket: int) -> int:
    Requires(total_shots >= 0)
    Requires(first_bucket >= 0)
    Requires(first_bucket <= total_shots)
    Ensures(Result() >= 0)
    Ensures(first_bucket + Result() == total_shots)

    return total_shots - first_bucket + 1


