import pytest

from magnet_evals.engines import ENGINE_SPECS, get_engine_spec


def test_engine_names():
    assert set(ENGINE_SPECS) == {'harbor', 'helm', 'olmo_eval', 'inspect_ai'}


def test_get_engine_spec():
    assert get_engine_spec('helm').module == 'helm'
    with pytest.raises(KeyError, match='unknown engine'):
        get_engine_spec('wat')
