from backend.app.main import _schedule_warmup_nonfatal


def test_warmup_scheduling_failure_is_nonfatal_and_later_warmups_can_run(caplog):
    calls = []

    def failed():
        calls.append("water")
        raise RuntimeError("thread creation failed")

    def next_warmup():
        calls.append("construction")

    _schedule_warmup_nonfatal("Water", failed)
    _schedule_warmup_nonfatal("Construction", next_warmup)

    assert calls == ["water", "construction"]
    assert "continuing startup" in caplog.text
