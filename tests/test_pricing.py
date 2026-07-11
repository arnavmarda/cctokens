from cctokens import pricing


def test_rate_lookup_by_substring():
    assert pricing.rate_for("claude-opus-4-8").input == 5.0
    assert pricing.rate_for("claude-sonnet-4-6").output == 15.0
    assert pricing.rate_for("claude-haiku-4-5").input == 1.0
    assert pricing.rate_for("claude-fable-5").output == 50.0
    assert pricing.rate_for("some-future-mythos").input == 10.0
    assert pricing.rate_for("gpt-4") is None
    assert pricing.rate_for(None) is None


def test_unknown_model_cost_is_none():
    assert pricing.cost_for("gpt-4", 100, 100, 0, 0) is None


def test_plain_input_output_cost():
    # opus: $5/1M in, $25/1M out
    cost = pricing.cost_for("claude-opus-4-8", 1_000_000, 1_000_000, 0, 0)
    assert cost == 30.0


def test_cache_read_is_tenth_of_input():
    # 1M cache-read tokens at opus = 0.1 * $5 = $0.50
    cost = pricing.cost_for("claude-opus-4-8", 0, 0, 0, 1_000_000)
    assert round(cost, 6) == 0.5


def test_cache_write_default_5m_rate():
    # No split provided -> whole creation bucket at 1.25x input
    cost = pricing.cost_for("claude-opus-4-8", 0, 0, 1_000_000, 0)
    assert round(cost, 6) == round(1.25 * 5.0, 6)


def test_cache_write_split_buckets():
    # 1M at 1h (2x) + 1M at 5m (1.25x), opus input $5/1M
    cost = pricing.cost_for(
        "claude-opus-4-8", 0, 0, 2_000_000, 0,
        cache_creation_1h=1_000_000, cache_creation_5m=1_000_000,
    )
    expected = 1_000_000 * (5.0 / 1e6) * 2.0 + 1_000_000 * (5.0 / 1e6) * 1.25
    assert round(cost, 6) == round(expected, 6)
