from strands import tool


@tool
def exact_match_scorer(actual_trajectory: list, expected_trajectory: list) -> float:
    """
    Score the trajectory based on exact match. A score of 0 indicates 0 steps matched and 1
    indicates a perfect match.

    Args:
        actual_trajectory: The actual trajectory.
        expected_trajectory: The expected trajectory.

    Returns:
        The score of the trajectory.
    """
    correct = 0
    for actual, expected in zip(actual_trajectory, expected_trajectory, strict=False):
        if actual == expected:
            correct += 1

    return correct / len(expected_trajectory)


@tool
def in_order_match_scorer(actual_trajectory: list, expected_trajectory: list) -> float:
    """
    Score based on correct actions in correct order, allows extra actions.

    Args:
        actual_trajectory: The actual trajectory.
        expected_trajectory: The expected trajectory.

    Returns:
        The score of the trajectory.
    """
    if not expected_trajectory:
        return 1.0

    expected_idx = 0
    for action in actual_trajectory:
        if expected_idx < len(expected_trajectory) and action == expected_trajectory[expected_idx]:
            expected_idx += 1

    return expected_idx / len(expected_trajectory)


@tool
def any_order_match_scorer(actual_trajectory: list, expected_trajectory: list) -> float:
    """
    Score based on correct actions in any order, allows extra actions.

    Args:
        actual_trajectory: The actual trajectory.
        expected_trajectory: The expected trajectory.

    Returns:
        The score of the trajectory.
    """
    if not expected_trajectory:
        return 1.0

    expected_set = set(expected_trajectory)
    actual_set = set(actual_trajectory)
    matched = len(expected_set.intersection(actual_set))

    return matched / len(expected_trajectory)
