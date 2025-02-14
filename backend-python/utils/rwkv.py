import os
import pathlib
from typing import Dict, List
from pydantic import BaseModel
from rwkv_pip.utils import PIPELINE


END_OF_TEXT = 0
END_OF_LINE = 187


os.environ["TORCH_EXTENSIONS_DIR"] = f"{pathlib.Path(__file__).parent.parent.resolve()}"


class RWKV:
    def __init__(self, model: str, strategy: str, tokens_path: str) -> None:
        from rwkv.model import RWKV as Model  # dynamic import to make RWKV_CUDA_ON work

        self.model = Model(model, strategy)
        self.pipeline = PIPELINE(self.model, tokens_path)
        self.model_state = None
        self.model_tokens = []

        self.CHUNK_LEN = 256

        self.max_tokens_per_generation = 500
        self.temperature = 1
        self.top_p = 0.5
        self.penalty_alpha_presence = 0.4
        self.penalty_alpha_frequency = 0.4

        self.interface = ":"
        if "rwkv_vocab" in tokens_path:
            self.user = "Human"
            self.bot = "Bot"
        else:
            self.user = "Bob"
            self.bot = "Alice"

        self.AVOID_REPEAT_TOKENS = []
        AVOID_REPEAT = "，：？！"
        for i in AVOID_REPEAT:
            dd = self.pipeline.encode(i)
            assert len(dd) == 1
            self.AVOID_REPEAT_TOKENS += dd

    def run_rnn(self, _tokens: List[str], newline_adj: int = 0):
        tokens = [int(x) for x in _tokens]
        self.model_tokens += tokens

        while len(tokens) > 0:
            out, self.model_state = self.model.forward(
                tokens[: self.CHUNK_LEN], self.model_state
            )
            tokens = tokens[self.CHUNK_LEN :]

        out[END_OF_LINE] += newline_adj  # adjust \n probability

        if self.model_tokens[-1] in self.AVOID_REPEAT_TOKENS:
            out[self.model_tokens[-1]] = -999999999
        return out

    def generate(self, prompt: str, stop: str = None):
        self.model_state = None
        self.model_tokens = []
        logits = self.run_rnn(self.pipeline.encode(prompt))
        begin = len(self.model_tokens)
        out_last = begin

        occurrence: Dict = {}

        response = ""
        for i in range(self.max_tokens_per_generation):
            for n in occurrence:
                logits[n] -= (
                    self.penalty_alpha_presence
                    + occurrence[n] * self.penalty_alpha_frequency
                )
            token = self.pipeline.sample_logits(
                logits, temperature=self.temperature, top_p=self.top_p
            )

            if token == END_OF_TEXT:
                break
            if token not in occurrence:
                occurrence[token] = 1
            else:
                occurrence[token] += 1

            logits = self.run_rnn([token])
            delta: str = self.pipeline.decode(self.model_tokens[out_last:])
            if "\ufffd" not in delta:  # avoid utf-8 display issues
                response += delta
                if stop is not None:
                    if stop in response:
                        response = response.split(stop)[0]
                        yield response, ""
                        break
                out_last = begin + i + 1
                yield response, delta


class ModelConfigBody(BaseModel):
    max_tokens: int = None
    temperature: float = None
    top_p: float = None
    presence_penalty: float = None
    frequency_penalty: float = None


def set_rwkv_config(model: RWKV, body: ModelConfigBody):
    if body.max_tokens:
        model.max_tokens_per_generation = body.max_tokens
    if body.temperature:
        model.temperature = body.temperature
    if body.top_p:
        model.top_p = body.top_p
    if body.presence_penalty:
        model.penalty_alpha_presence = body.presence_penalty
    if body.frequency_penalty:
        model.penalty_alpha_frequency = body.frequency_penalty


def get_rwkv_config(model: RWKV) -> ModelConfigBody:
    return ModelConfigBody(
        max_tokens=model.max_tokens_per_generation,
        temperature=model.temperature,
        top_p=model.top_p,
        presence_penalty=model.penalty_alpha_presence,
        frequency_penalty=model.penalty_alpha_frequency,
    )
