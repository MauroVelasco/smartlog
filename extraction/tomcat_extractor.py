"""
Tomcat log extraction — second source brought online in business case
slide 10 stage 1 ("One client's CloudWatch + Tomcat logs").

Reads catalina.out / localhost_access_log files (plain or .gz, e.g. after
logrotate) from local disk or an already-mounted volume / EFS path. If
Tomcat output is instead shipped into CloudWatch via the unified agent,
point CLOUDWATCH_LOG_GROUPS at that log group instead — this extractor
is only needed when Tomcat logs live on disk.

Tomcat entries are frequently multi-line (a timestamped header line
followed by an unindented Java stack trace). This extractor groups each
header line with its continuation lines into a single logical
RawLogRecord, so normalization sees the whole exception, not just its
first line. Timestamp *parsing* still happens in normalization —
extraction only needs to know where one record ends and the next
begins, which it does with the same header-line shape without doing a
full date parse.
"""
from __future__ import annotations

import gzip
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import IO, Iterable, List

import config
from extraction.base import BaseExtractor
from models.schema import RawLogRecord, SourceSystem

logger = logging.getLogger(__name__)

# Matches the start of a new Tomcat log entry: default Tomcat 9/10
# `dd-MMM-yyyy HH:mm:ss.SSS` juli format, or the older
# `yyyy-MM-dd HH:mm:ss` / access-log-style leading timestamp. This is
# intentionally the same shape normalization's _TOMCAT_TS_PATTERN
# matches against — here it's only used to find record boundaries, not
# to parse a datetime.
_ENTRY_START_PATTERN = re.compile(
    r"^(\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2}\.\d{3}|\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
)

_MAX_LINES_PER_ENTRY = 500  # guard against an unbounded stack trace / binary garbage


class TomcatExtractor(BaseExtractor):
    source_system = SourceSystem.TOMCAT.value

    def __init__(self, log_paths: List[str] = None):
        self.log_paths = log_paths or config.TOMCAT_LOG_PATHS

    def extract(self, start_time: datetime, end_time: datetime) -> List[RawLogRecord]:
        records: List[RawLogRecord] = []
        for path_str in self.log_paths:
            for path in self._resolve_paths(path_str):
                records.extend(self._extract_file(path))
        return records

    def _resolve_paths(self, path_str: str) -> Iterable[Path]:
        """Expand a glob (e.g. '/var/log/tomcat/catalina.*.log*') into
        concrete files, plain or gzipped, so rotated logs are picked up
        without extra config."""
        raw_path = Path(path_str)
        if any(ch in path_str for ch in "*?["):
            matches = sorted(raw_path.parent.glob(raw_path.name))
            if not matches:
                logger.warning("No files matched Tomcat log glob: %s", path_str)
            return matches
        if not raw_path.exists():
            logger.warning("Tomcat log path not found: %s", raw_path)
            return []
        return [raw_path]

    def _open(self, path: Path) -> IO[str]:
        if path.suffix == ".gz":
            return gzip.open(path, mode="rt", errors="replace")
        return path.open("r", errors="replace")

    def _extract_file(self, path: Path) -> List[RawLogRecord]:
        records: List[RawLogRecord] = []
        entry_lines: List[str] = []
        entry_start_line_no = None

        def flush(end_line_no: int):
            if not entry_lines:
                return
            records.append(
                RawLogRecord(
                    source_system=SourceSystem.TOMCAT,
                    origin=f"{path}:{entry_start_line_no}-{end_line_no}",
                    raw_payload={"line": "\n".join(entry_lines)},
                )
            )

        try:
            with self._open(path) as fh:
                for line_no, raw_line in enumerate(fh, start=1):
                    line = raw_line.rstrip("\n")
                    if not line.strip():
                        continue
                    if _ENTRY_START_PATTERN.match(line):
                        flush(line_no - 1)
                        entry_lines = [line]
                        entry_start_line_no = line_no
                    elif entry_lines:
                        # Continuation line (e.g. stack trace frame) — stitch
                        # onto the current entry, bounded so a corrupt file
                        # can't produce an unbounded record.
                        if len(entry_lines) < _MAX_LINES_PER_ENTRY:
                            entry_lines.append(line)
                    else:
                        # File doesn't start with a recognizable header
                        # (e.g. access log with a different format) — treat
                        # every line as its own record.
                        records.append(
                            RawLogRecord(
                                source_system=SourceSystem.TOMCAT,
                                origin=f"{path}:{line_no}",
                                raw_payload={"line": line},
                            )
                        )
                flush(line_no if "line_no" in locals() else 0)
        except OSError as exc:
            logger.warning("Failed to read Tomcat log file %s: %s", path, exc)

        logger.info("Tomcat extraction: %s -> %d records", path, len(records))
        return records
