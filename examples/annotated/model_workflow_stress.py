# Proofside end-to-end stress-test fixture.
#
# The annotations are the intended specification. Some implementations satisfy
# that specification and some do not. There are no bug labels in this file so
# the proposal model has to work only from the declared equation/intent.


# proofside equation: result = value
# proofside intent: Return the input count unchanged.
def carry_forward(value: int) -> int:
    result = value
    return result


# proofside equation: result = first + second
# proofside intent: Return the total of two nonnegative measurement counts.
def combine_counts(first: int, second: int) -> int:
    result = first + second
    return result


# proofside equation: used + result = total
# proofside intent: Return the unused portion of the budget.
# proofside intent: total and used are nonnegative, and used must not exceed total.
def unused_budget(total: int, used: int) -> int:
    result = total - used
    return result


# proofside equation: used + result = total
# proofside intent: Return the unused portion of the budget exactly.
# proofside intent: total and used are nonnegative, and used must not exceed total.
def held_out_budget(total: int, used: int) -> int:
    result = total - used + 1
    return result


# proofside equation: result = first + second + third
# proofside intent: Return the sum of three independently supplied counts.
def aggregate_three(first: int, second: int, third: int) -> int:
    partial = first + second
    result = partial + second
    return result


# proofside intent: Return a value that is always nonnegative.
# proofside intent: Preserve the input when it is already nonnegative; otherwise return zero.
def nonnegative_part(value: int) -> int:
    if value >= 0:
        result = value
    else:
        result = 0
    return result


# proofside intent: Return a value that is always nonnegative.
# proofside intent: Preserve the input when it is already nonnegative; otherwise return zero.
def sanitized_residual(value: int) -> int:
    if value >= 0:
        result = value
    else:
        result = -1
    return result


# proofside equation: training + testing + result = total
# proofside intent: Return the shots left after training and testing allocations.
# proofside intent: All counts are nonnegative and training + testing must not exceed total.
def remaining_shots(total: int, training: int, testing: int) -> int:
    allocated = training + testing
    result = total - allocated
    return result
