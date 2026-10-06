import pytest

from calc import divide


def test_ordinary_division():
    assert divide(6, 2) == 3


def test_zero_denominator():
    with pytest.raises(ValueError, match="^zero denominator$"):
        divide(3, 0)
