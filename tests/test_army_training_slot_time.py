import pytest

from army_training_slot_time import SECONDS_PER_DAY, SECONDS_PER_HOUR, _read_number, _split_label, read_slot_training_time
from army_training_slots import find_slots
from tools.resource_ocr import read_image

FIXTURES = "screenshots/army_training"
EXPECTED = {
    "pelny": [(11, 15), (11, 15), (11, 4)],
    "pelny_army_training_empty_queue": [(14, 11), (15, 2), (15, 3)],
}


@pytest.fixture(scope="module", params=sorted(EXPECTED))
def readings(request):
    path = f"{FIXTURES}/{request.param}.png"
    image = read_image(path)
    return request.param, [read_slot_training_time(image, slot) for slot in find_slots(path).slots]


def test_fixture_times_match_the_displayed_days_and_hours(readings):
    name, values = readings
    expected = [days * SECONDS_PER_DAY + hours * SECONDS_PER_HOUR for days, hours in EXPECTED[name]]

    assert [reading.value for reading in values] == expected
    assert all(reading.confidence == 100.0 for reading in values)


def comp(x, width=6, height=9):
    return (x, 6, width, height, 26)


DOT = (0, 14, 2, 2, 3)


def label(days, hours):
    return [*days, comp(40, 8, 12), (51, 14, 2, 2, 3), *hours, comp(79, 7, 12), (88, 14, 2, 2, 3)]


def test_split_requires_d_and_g_markers_between_digit_groups():
    parts = _split_label(label([comp(22), comp(29)], [comp(59), comp(67)]))
    assert [len(group) for group in parts] == [2, 2]


def test_agreeing_unverified_digit_is_not_accepted(monkeypatch):
    monkeypatch.setattr("army_training_slot_time._read_digit", lambda gray, digit, scale: "8")

    assert _read_number(None, [comp(22)]) is None


@pytest.mark.parametrize("components", [
    label([comp(22, 14)], [comp(59)]),  # merged "11" must not pass as one digit
    label([], [comp(59)]),
    label([comp(22)], []),
    label([comp(22)] * 4, [comp(59)]),
    label([comp(22)], [comp(59)])[:-1],  # trailing dot missing
])
def test_split_rejects_ambiguous_layouts(components):
    assert _split_label(components) is None
