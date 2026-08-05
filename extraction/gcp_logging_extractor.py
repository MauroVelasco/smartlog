"""
GCP Logging extraction — business case slide 10 stage 2 ("Expand &
harden": add GCP + DB sources). Disabled by default in the POC
(CloudWatch is the primary/active source); wired up now so enabling it
later is a config flag, not new code.

Requires: pip install google-cloud-logging, and either
GOOGLE_APPLICATION_CREDENTIALS pointing at a service account with
roles/logging.viewer, or ambient credentials (gcloud auth application-default
login) when run from a workstation.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

import config
from extraction.base import BaseExtractor
from models.schema import RawLogRecord, SourceSystem

logger = logging.getLogger(__name__)

_MAX_ENTRIES = 20_000  # guardrail so one wide filter can't pull an unbounded result set


class GCPLoggingExtractor(BaseExtractor):
    source_system = SourceSystem.GCP_LOGGING.value

    def __init__(self, project_id: Optional[str] = None, log_filter: str = "", max_entries: int = _MAX_ENTRIES):
        self.project_id = project_id or config.GCP_PROJECT_ID
        self.log_filter = log_filter or config.GCP_LOG_FILTER
        self.max_entries = max_entries

    def extract(self, start_time: datetime, end_time: datetime) -> List[RawLogRecord]:
        try:
            from google.cloud import logging as gcp_logging  # local import: optional dep
        except ImportError:
            logger.warning(
                "google-cloud-logging not installed; skipping GCP extraction. "
                "Run `pip install google-cloud-logging` to enable this source."
            )
            return []

        if not self.project_id:
            logger.warning("GCP_PROJECT_ID not set; skipping GCP extraction.")
            return []

        client = gcp_logging.Client(project=self.project_id)
        start_iso = start_time.astimezone(timezone.utc).isoformat()
        end_iso = end_time.astimezone(timezone.utc).isoformat()
        time_filter = f'timestamp >= "{start_iso}" AND timestamp < "{end_iso}"'
        full_filter = f"{time_filter} AND ({self.log_filter})" if self.log_filter else time_filter

        records: List[RawLogRecord] = []
        try:
            iterator = client.list_entries(filter_=full_filter, order_by=gcp_logging.ASCENDING)
            for entry in iterator:
                records.append(self._entry_to_record(entry))
                if len(records) >= self.max_entries:
                    logger.warning(
                        "GCP extraction hit max_entries=%d cap; narrow GCP_LOG_FILTER or the time window.",
                        self.max_entries,
                    )
                    break
        except Exception as exc:  # pragma: no cover - depends on live GCP project
            logger.warning("GCP Logging extraction failed: %s", exc)

        return records

    @staticmethod
    def _entry_to_record(entry) -> RawLogRecord:
        message, payload_type = GCPLoggingExtractor._flatten_payload(entry.payload)
        labels = dict(entry.labels) if getattr(entry, "labels", None) else {}
        resource_labels = dict(entry.resource.labels) if entry.resource and entry.resource.labels else {}
        return RawLogRecord(
            source_system=SourceSystem.GCP_LOGGING,
            origin=entry.log_name or "gcp_logging",
            raw_payload={
                "message": message,
                "payload_type": payload_type,
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                "severity": entry.severity,
                "resource_type": entry.resource.type if entry.resource else None,
                "resource_labels": resource_labels,
                "labels": labels,
                "insert_id": entry.insert_id,
                "trace": getattr(entry, "trace", None),
            },
        )

    @staticmethod
    def _flatten_payload(payload) -> tuple[str, str]:
        """GCP entries can carry a plain string (textPayload), a dict
        (jsonPayload), or a proto (protoPayload). Flatten all three into
        a single text blob so normalization's identifier regexes can
        run over it the same way they do for every other source."""
        if payload is None:
            return "", "empty"
        if isinstance(payload, str):
            return payload, "text"
        if isinstance(payload, dict):
            # Common structured-logging keys first, for a readable summary;
            # fall back to the full JSON so nothing is lost for correlation.
            for key in ("message", "msg", "error", "description"):
                if key in payload and isinstance(payload[key], str):
                    return f"{payload[key]} | {json.dumps(payload)}", "json"
            return json.dumps(payload), "json"
        return str(payload), "proto"
