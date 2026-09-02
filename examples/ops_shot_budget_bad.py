def remaining_feature_shots(
    total_shots: int,
    training_feature_shots: int,
    test_feature_shots: int,
) -> int:
    return total_shots - training_feature_shots - test_feature_shots + 1
