# proofside equation: result = total_shots - first_bucket
# proofside intent: Return the unallocated portion of a nonnegative total budget.
def allocate_remaining(total_shots: int, first_bucket: int) -> int:
    return total_shots - first_bucket
