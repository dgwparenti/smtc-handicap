from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture()
def email_mailchimp(fixtures_dir):
    return (fixtures_dir / "email_results_mailchimp_link.html").read_text()


@pytest.fixture()
def email_direct_cdn(fixtures_dir):
    return (fixtures_dir / "email_results_direct_cdn.html").read_text()


@pytest.fixture()
def email_draw_only(fixtures_dir):
    return (fixtures_dir / "email_draw_only.html").read_text()


@pytest.fixture()
def email_no_link(fixtures_dir):
    return (fixtures_dir / "email_no_link.html").read_text()


@pytest.fixture()
def email_both(fixtures_dir):
    return (fixtures_dir / "email_both_results_and_draw.html").read_text()


@pytest.fixture()
def email_practice_direct_cdn(fixtures_dir):
    return (fixtures_dir / "email_practice_direct_cdn.html").read_text()
