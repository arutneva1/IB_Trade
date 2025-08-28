from typing import Any

class Result:
    exit_code: int

class CliRunner:
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
    def invoke(self, *args: Any, **kwargs: Any) -> Result: ...
