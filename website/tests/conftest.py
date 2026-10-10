"""Portable historical and fictional demo data for the entire test suite."""
import pytest

from legacy_fixtures import create_legacy_database


@pytest.fixture
def legacy_database_factory(tmp_path):
    return lambda version: create_legacy_database(tmp_path / f'legacy-v{version}.sqlite3', version)


@pytest.fixture(scope='session')
def three_season_database(tmp_path_factory):
    from demo.generate_three_seasons import generate
    path = tmp_path_factory.mktemp('fictional-three-seasons') / 'league.sqlite3'
    generate(path)
    return path
