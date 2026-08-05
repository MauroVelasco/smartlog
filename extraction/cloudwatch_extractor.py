"""
Primary extraction point for the POC (business case slide 10, stage 1).

Pulls events from one or more CloudWatch Logs log groups via
`filter_log_events`, handling pagination and rate limiting, and hands
back raw, unparsed records. All log-format-specific parsing happens in
normalization/normalizer.py, not here — this module's only job is
reliable extraction from AWS.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

import config
from extraction.base import BaseExtractor
from models.schema import RawLogRecord, SourceSystem

logger = logging.getLogger(__name__)


def _to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class CloudWatchExtractor(BaseExtractor):
    """Extracts log events from AWS CloudWatch Logs.

    One instance per log group keeps retry/pagination logic simple and
    lets callers parallelize across groups if the POC's log volume
    requires it later.
    """

    source_system = SourceSystem.CLOUDWATCH.value

    def __init__(
        self,
        log_groups: Optional[List[str]] = None,
        filter_pattern: str = "",
        region_name: Optional[str] = None,
        max_events_per_group: int = 10_000,
    ):
        self.log_groups = log_groups or config.CLOUDWATCH_LOG_GROUPS
        self.filter_pattern = filter_pattern or config.CLOUDWATCH_FILTER_PATTERN
        self.max_events_per_group = max_events_per_group
        self._client = boto3.client(
            "logs",
            region_name=region_name or config.AWS_REGION,
            config=BotoConfig(retries={"max_attempts": 5, "mode": "adaptive"}),
        )

    def extract(self, start_time: datetime, end_time: datetime) -> List[RawLogRecord]:
        records: List[RawLogRecord] = []
        for log_group in self.log_groups:
            try:
                records.extend(self._extract_one_group(log_group, start_time, end_time))
            except ClientError as exc:
                # Don't let one missing/inaccessible log group kill the whole
                # extraction run — log and continue with the rest.
                logger.warning("CloudWatch extraction failed for %s: %s", log_group, exc)
        return records

    def _extract_one_group(
        self, log_group: str, start_time: datetime, end_time: datetime
    ) -> List[RawLogRecord]:
        records: List[RawLogRecord] = []
        kwargs = {
            "logGroupName": log_group,
            "startTime": _to_ms(start_time),
            "endTime": _to_ms(end_time),
            "interleaved": True,
        }
        if self.filter_pattern:
            kwargs["filterPattern"] = self.filter_pattern

        next_token = None
        while True:
            if next_token:
                kwargs["nextToken"] = next_token
            response = self._call_with_backoff(**kwargs)
            for event in response.get("events", []):
                records.append(
                    RawLogRecord(
                        source_system=SourceSystem.CLOUDWATCH,
                        origin=f"{log_group}:{event.get('logStreamName', '')}",
                        raw_payload={
                            "message": event.get("message", ""),
                            "timestamp_ms": event.get("timestamp"),
                            "log_stream_name": event.get("logStreamName"),
                            "event_id": event.get("eventId"),
                        },
                    )
                )
                if len(records) >= self.max_events_per_group:
                    return records
            next_token = response.get("nextToken")
            if not next_token:
                break
        return records

    def _call_with_backoff(self, **kwargs):
        delay = 1.0
        for attempt in range(5):
            try:
                return self._client.filter_log_events(**kwargs)
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") != "ThrottlingException" or attempt == 4:
                    raise
                time.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")  # pragma: no cover
