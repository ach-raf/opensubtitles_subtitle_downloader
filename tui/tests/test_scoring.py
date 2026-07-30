import pytest

from library.subtitle_utils import SubtitleUtils


@pytest.fixture
def scorer():
    return SubtitleUtils()


PITT_QUERY = (
    "The Pitt (2025) - S01E01 - - 7-00 A.M "
    "[AMZN Flux WEBDL-1080p Proper][8bit][h264][EAC3 Atmos 5.1]-FLUX"
)
UNRELATED_S01E01 = (
    "The.World.of.the.Married.S01E01.720p.WEB-DL.x264-Pahe.in"
)


def test_same_series_conflicts_outrank_unrelated_exact_episode(scorer):
    exact = scorer.score_subtitle(
        "The.Pitt.S01E01.1080p.WEB.H264-SuccessfulCrab",
        PITT_QUERY,
    )
    wrong_season = scorer.score_subtitle(
        "The.Pitt.S02E01.1080p.WEB.h264-ETHEL.ar",
        PITT_QUERY,
    )
    wrong_episode = scorer.score_subtitle(
        "The.Pitt.S01E02.1080p.WEB.H264-SuccessfulCrab",
        PITT_QUERY,
    )
    unrelated = scorer.score_subtitle(UNRELATED_S01E01, PITT_QUERY)

    assert exact > wrong_season > unrelated
    assert exact > wrong_episode > unrelated


def test_same_series_with_unknown_episode_outranks_unrelated_exact_episode(scorer):
    same_series_unknown_episode = scorer.score_subtitle(
        "The.Pitt.Arabic.WEB-DL",
        PITT_QUERY,
    )
    unrelated = scorer.score_subtitle(UNRELATED_S01E01, PITT_QUERY)

    assert same_series_unknown_episode > unrelated


@pytest.mark.parametrize(
    "matching_release",
    [
        "Hajime no Ippo – 42 [ALOIN][DVD]",
        "Hajime no Ippo Round 42 [DVD]",
        "Hajime no Ippo 42 END [DVD]",
    ],
)
def test_labeled_or_bare_episode_adds_a_bounded_nudge(scorer, matching_release):
    query = "Hajime no Ippo S01E42 1080p"
    matching = scorer.score_subtitle(matching_release, query)
    unknown = scorer.score_subtitle("Hajime no Ippo Special [DVD]", query)

    assert matching >= unknown + 5


def test_bare_episode_does_not_treat_year_or_resolution_as_episode(scorer):
    query = "Movie S01E24"
    neutral = scorer.score_subtitle("Movie Special", query)
    year = scorer.score_subtitle("Movie - 2024", query)
    resolution = scorer.score_subtitle("Movie - 24 1080p", query)

    assert year <= neutral + 2
    assert resolution <= neutral + 2


def test_one_shared_generic_title_token_does_not_establish_same_series(scorer):
    misleading = scorer.score_subtitle(
        "World Trigger S01E01",
        "World News S01E01",
    )
    same_title_unknown_episode = scorer.score_subtitle(
        "World News Special",
        "World News S01E01",
    )

    assert same_title_unknown_episode > misleading
