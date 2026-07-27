from vgm_bridge.models import Decision


def test_weights_sum_to_one():
    decision = Decision(
        schema_version="1.0",
        decision_id="d1",
        simulation_id="s1",
        period="2016-07",
        input_state_hash="abc",
        action="hold",
        target_weights={"CASH": 1.0},
        rationale="No evidence supplied.",
        confidence=0.2,
    )
    assert sum(decision.target_weights.values()) == 1.0
