import json

from shared.health import _metadata


def test_metadata_serializes_values_and_unicode():
    value = json.loads(_metadata({'symbol': 'بيتكوين', 'count': 2}))
    assert value == {'symbol': 'بيتكوين', 'count': 2}


def test_metadata_defaults_to_empty_object():
    assert json.loads(_metadata(None)) == {}
