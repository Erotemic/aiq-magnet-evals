from magnet_evals.probes.api_surface import API_SURFACES, resolve_symbol


def test_surfaces_cover_engines():
    assert set(API_SURFACES) == {'harbor', 'helm', 'olmo_eval', 'inspect_ai'}


def test_resolve_symbol():
    assert resolve_symbol('pathlib', 'Path').__name__ == 'Path'
