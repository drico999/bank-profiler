import json
import pytest

from profiler.synthetic import generate_all


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    d = tmp_path_factory.mktemp("samples")
    generate_all(d)
    return d


def truth(samples, persona):
    return json.loads((samples / f"{persona}.truth.json").read_text())


class _Block:
    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]


class FakeClient:
    """Mimics client.messages.create(...). `reply` is a function(prompt_text)->str."""
    def __init__(self, reply):
        self.reply, self.prompts = reply, []
        self.messages = self

    def create(self, **kw):
        self.prompts.append(kw["messages"][0]["content"])
        return _Resp(self.reply(kw["messages"][0]["content"]))
