import gzip
from pathlib import Path

from extraction.tomcat_extractor import TomcatExtractor
from models.schema import SourceSystem

CATALINA_SAMPLE = """04-Aug-2026 12:00:00.123 SEVERE [http-nio-8080-exec-3] com.example.OrderService.process request_id=req-abc123 NullPointerException
\tat com.example.OrderService.process(OrderService.java:42)
\tat com.example.OrderController.handle(OrderController.java:17)
04-Aug-2026 12:00:05.456 INFO [http-nio-8080-exec-4] com.example.OrderController.handle request_id=req-def456 request handled
"""


def test_stitches_stack_trace_into_one_record(tmp_path: Path):
    log_file = tmp_path / "catalina.out"
    log_file.write_text(CATALINA_SAMPLE)

    extractor = TomcatExtractor(log_paths=[str(log_file)])
    records = extractor.extract(start_time=None, end_time=None)  # not time-filtered at extraction

    assert len(records) == 2
    first = records[0]
    assert first.source_system == SourceSystem.TOMCAT
    assert "NullPointerException" in first.raw_payload["line"]
    assert "at com.example.OrderService.process" in first.raw_payload["line"]
    assert "at com.example.OrderController.handle" in first.raw_payload["line"]

    second = records[1]
    assert "request handled" in second.raw_payload["line"]
    assert "at com.example" not in second.raw_payload["line"]


def test_reads_gzipped_rotated_log(tmp_path: Path):
    log_file = tmp_path / "catalina.2026-08-03.log.gz"
    with gzip.open(log_file, "wt") as fh:
        fh.write("03-Aug-2026 23:59:00.000 INFO [main] startup complete\n")

    extractor = TomcatExtractor(log_paths=[str(tmp_path / "catalina.*.log.gz")])
    records = extractor.extract(start_time=None, end_time=None)

    assert len(records) == 1
    assert "startup complete" in records[0].raw_payload["line"]


def test_missing_path_returns_empty_without_raising(tmp_path: Path):
    extractor = TomcatExtractor(log_paths=[str(tmp_path / "does_not_exist.out")])
    assert extractor.extract(start_time=None, end_time=None) == []
