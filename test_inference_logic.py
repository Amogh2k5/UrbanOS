"""Quick inference logic verification tests"""
import numpy as np

def test_inference_logic():
    """Test the corrected inference formula"""
    
    # Simulate the corrected logic
    def compute_prediction(cur_speed, predicted_change):
        cur_speed = max(0.0, min(cur_speed, 120.0))
        pred_speed = cur_speed + predicted_change
        pred_speed = max(0.0, min(pred_speed, 120.0))
        max_drop = 0.30 * cur_speed
        if cur_speed - pred_speed > max_drop:
            pred_speed = cur_speed - max_drop
            predicted_change = pred_speed - cur_speed
        return pred_speed, predicted_change
    
    print("Testing corrected inference logic:")
    print("=" * 60)
    
    # Test 1: Positive Δspeed increases current speed
    cur, change = 50.0, 10.0
    pred, actual_change = compute_prediction(cur, change)
    assert pred == 60.0, f"Expected 60.0, got {pred}"
    assert actual_change == 10.0, f"Expected 10.0, got {actual_change}"
    print(f"[OK] Positive delta: cur={cur}, change={change} -> pred={pred}, actual_change={actual_change}")
    
    # Test 2: Negative Δspeed decreases current speed
    cur, change = 50.0, -5.0
    pred, actual_change = compute_prediction(cur, change)
    assert pred == 45.0, f"Expected 45.0, got {pred}"
    assert actual_change == -5.0, f"Expected -5.0, got {actual_change}"
    print(f"[OK] Negative delta: cur={cur}, change={change} -> pred={pred}, actual_change={actual_change}")
    
    # Test 3: Zero Δspeed preserves current speed
    cur, change = 50.0, 0.0
    pred, actual_change = compute_prediction(cur, change)
    assert pred == 50.0, f"Expected 50.0, got {pred}"
    assert actual_change == 0.0, f"Expected 0.0, got {actual_change}"
    print(f"[OK] Zero delta: cur={cur}, change={change} -> pred={pred}, actual_change={actual_change}")
    
    # Test 4: Upper clipping (pred > 120) - note: predictor doesn't adjust change for upper clip
    cur, change = 115.0, 20.0
    pred, actual_change = compute_prediction(cur, change)
    assert pred == 120.0, f"Expected 120.0, got {pred}"
    # Predictor doesn't adjust change for upper clip (only for 30% drop guard)
    # So actual_change remains 20.0 (the model's raw output)
    assert actual_change == 20.0, f"Expected 20.0 (unchanged), got {actual_change}"
    print(f"[OK] Upper clip: cur={cur}, change={change} -> pred={pred}, actual_change={actual_change}")
    
    # Test 5: Lower clipping + 30% drop guard triggers
    cur, change = 10.0, -20.0
    pred, actual_change = compute_prediction(cur, change)
    # 30% drop guard triggers: max drop = 3, so pred = 7, change = -3
    assert pred == 7.0, f"Expected 7.0 (30% drop), got {pred}"
    assert actual_change == -3.0, f"Expected -3.0 (adjusted), got {actual_change}"
    print(f"[OK] Lower clip + 30% guard: cur={cur}, change={change} -> pred={pred}, actual_change={actual_change}")
    
    # Test 6: 30% drop guard
    cur, change = 100.0, -40.0  # 40% drop, should be capped at 30%
    pred, actual_change = compute_prediction(cur, change)
    assert pred == 70.0, f"Expected 70.0 (30% drop), got {pred}"
    assert actual_change == -30.0, f"Expected -30.0, got {actual_change}"
    print(f"[OK] 30% drop guard: cur={cur}, change={change} -> pred={pred}, actual_change={actual_change}")
    
    # Test 7: Negative current speed (should clip to 0 internally)
    cur, change = -10.0, 5.0
    pred, actual_change = compute_prediction(cur, change)
    # cur is clipped to 0 internally, so pred = 0 + 5 = 5
    assert pred == 5.0, f"Expected 5.0, got {pred}"
    assert actual_change == 5.0, f"Expected 5.0, got {actual_change}"
    print(f"[OK] Negative cur clip: cur={cur}, change={change} -> pred={pred}")
    
    print("\n" + "=" * 60)
    print("All inference logic tests PASSED!")
    return True

if __name__ == "__main__":
    test_inference_logic()