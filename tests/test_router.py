import json

import pytest

from habermk.llm.providers import ModelError
from habermk.llm.router import AllModelsFailed, ModelSpec, Router

OK = json.dumps({"status": "OK", "sentence": "А.", "evidence": "б", "scope": "MK", "reason": ""})


class Fake:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def complete(self, model, system, messages, temperature, params):
        self.calls += 1
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make(providers, specs=("a:m1", "b:m2")):
    sleeps = []
    router = Router([ModelSpec(id=s) for s in specs], providers=providers,
                    sleep=sleeps.append, clock=lambda: 0.0)
    return router, sleeps


def test_first_model_answers():
    router, _ = make({"a": Fake(OK), "b": Fake(OK)})
    result, model = router.generate("Наслов", "СДК", "текст")
    assert model == "a:m1" and result["status"] == "OK"


def test_rate_limit_is_retried_once_then_succeeds():
    a = Fake(ModelError("429", retryable=True, retry_after=12), OK)
    router, sleeps = make({"a": a, "b": Fake(OK)})
    assert router.generate("Н", "С", "т")[1] == "a:m1"
    assert a.calls == 2 and 12 in sleeps


def test_falls_back_when_first_model_is_down():
    a = Fake(ModelError("500", retryable=True), ModelError("500", retryable=True))
    router, _ = make({"a": a, "b": Fake(OK)})
    assert router.generate("Н", "С", "т")[1] == "b:m2"


def test_non_retryable_error_falls_back_immediately():
    a = Fake(ModelError("bad key"))
    router, _ = make({"a": a, "b": Fake(OK)})
    assert router.generate("Н", "С", "т")[1] == "b:m2" and a.calls == 1


def test_invalid_json_is_retried():
    router, _ = make({"a": Fake("not json", OK), "b": Fake(OK)})
    assert router.generate("Н", "С", "т")[1] == "a:m1"


def test_all_models_failed():
    router, _ = make({"a": Fake("x", "y"), "b": Fake(ModelError("down"))})
    with pytest.raises(AllModelsFailed):
        router.generate("Н", "С", "т")


def test_throttle_waits_between_calls():
    clock = iter([0.0, 5.0, 5.0])
    router = Router([ModelSpec(id="a:m", min_interval_s=25)], providers={"a": Fake(OK, OK)},
                    sleep=(sleeps := []).append, clock=lambda: next(clock))
    router.generate("Н", "С", "т")
    router.generate("Н", "С", "т")
    assert sleeps == [20.0]


def test_long_rate_limit_rests_the_model_instead_of_sleeping():
    wall = [1000.0]
    a = Fake(ModelError("daily quota", retryable=True, retry_after=3600))
    sleeps = []
    router = Router([ModelSpec(id="a:m1"), ModelSpec(id="b:m2")],
                    providers={"a": a, "b": Fake(OK, OK)}, sleep=sleeps.append,
                    clock=lambda: 0.0, wall=lambda: wall[0])
    assert router.generate("Н", "С", "т")[1] == "b:m2"
    assert sleeps == [] and a.calls == 1
    assert router.cooldown_until["a:m1"] == 4600.0
    # still resting on the next story: not even called
    assert router.generate("Н", "С", "т")[1] == "b:m2" and a.calls == 1
    wall[0] = 5000.0
    assert [s.id for s in router.available()] == ["a:m1", "b:m2"]


def test_all_models_resting_raises_cooling():
    from habermk.llm.router import AllModelsCooling

    router = Router([ModelSpec(id="a:m1")], providers={"a": Fake()}, wall=lambda: 10.0)
    router.cooldown_until["a:m1"] = 99.0
    with pytest.raises(AllModelsCooling):
        router.generate("Н", "С", "т")
    assert router.active_cooldowns() == {"a:m1": 99.0}
