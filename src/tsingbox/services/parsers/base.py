from __future__ import annotations

from abc import ABC, abstractmethod


class ParseError(ValueError):
    pass


class BaseParser(ABC):
    scheme: str

    @abstractmethod
    def parse(self, uri: str) -> dict:
        raise NotImplementedError
