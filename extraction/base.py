"""
Common interface every Log Source extractor implements. Keeping this
narrow is what lets the POC start with CloudWatch only and expand to
Tomcat / GCP Logging / Oracle-MySQL-Postgres (business case slide 10,
stage 2 "Expand & harden") without touching normalization, correlation,
storage, or the UI.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List

from models.schema import RawLogRecord


class BaseExtractor(ABC):
    source_system: str

    @abstractmethod
    def extract(self, start_time: datetime, end_time: datetime) -> List[RawLogRecord]:
        """Pull raw records for [start_time, end_time) and return them
        untouched — normalization happens in the next stage."""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{self.__class__.__name__} source={self.source_system}>"
