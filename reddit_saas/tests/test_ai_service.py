"""Test AI service — cost calculation, no actual LLM calls."""

from app.services.ai import _calculate_cost


def test_cost_calculation_sonnet():
    cost = _calculate_cost("anthropic/claude-sonnet-4-20250514", input_tokens=10000, output_tokens=500)
    # input: 10000/1M * 3.00 = 0.03
    # output: 500/1M * 15.00 = 0.0075
    assert abs(cost - 0.0375) < 0.001


def test_cost_calculation_haiku():
    cost = _calculate_cost("anthropic/claude-3-5-haiku-20241022", input_tokens=5000, output_tokens=200)
    # input: 5000/1M * 0.80 = 0.004
    # output: 200/1M * 4.00 = 0.0008
    assert abs(cost - 0.0048) < 0.001


def test_cost_calculation_gemini():
    cost = _calculate_cost("gemini/gemini-2.0-flash", input_tokens=4000, output_tokens=200)
    # input: 4000/1M * 0.075 = 0.0003
    # output: 200/1M * 0.30 = 0.00006
    assert abs(cost - 0.00036) < 0.0001


def test_cost_unknown_model():
    cost = _calculate_cost("unknown/model", input_tokens=1000, output_tokens=100)
    assert cost == 0.0


def test_cost_zero_tokens():
    cost = _calculate_cost("anthropic/claude-sonnet-4-20250514", input_tokens=0, output_tokens=0)
    assert cost == 0.0
