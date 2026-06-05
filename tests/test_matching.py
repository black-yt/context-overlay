from context_overlay.config import MatchConfig
from context_overlay.matching import request_matches


def test_request_matches_message_regex() -> None:
    body = {
        "model": "m",
        "messages": [{"role": "user", "content": "Run a scientific analysis"}],
    }
    match = MatchConfig(path="/v1/chat/completions", messages_regex=["scientific"])
    assert request_matches("/v1/chat/completions", body, match)


def test_request_match_requires_all_message_patterns() -> None:
    body = {"messages": [{"role": "user", "content": "scientific"}]}
    match = MatchConfig(messages_regex=["scientific", "missing"])
    assert not request_matches("/v1/chat/completions", body, match)


def test_request_matches_extra_body() -> None:
    body = {"profile": "rcb", "messages": []}
    assert request_matches("/v1/chat/completions", body, MatchConfig(extra_body={"profile": "rcb"}))
    assert not request_matches("/v1/chat/completions", body, MatchConfig(extra_body={"profile": "other"}))
