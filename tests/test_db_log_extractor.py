from extraction.db_log_extractor import PostgresLogFileExtractor

PG_LOG_SAMPLE = (
    "2026-08-04 12:00:00.123 UTC [12345] ERROR:  duration: 12.345 ms  request_id=req-abc123\n"
    "\tstatement: SELECT * FROM orders WHERE id = $1\n"
    "2026-08-04 12:00:05.789 UTC [12346] LOG:  connection authorized: user=app database=orders\n"
)


def test_parses_postgres_log_text_into_records():
    extractor = PostgresLogFileExtractor(connection_name="app")
    records = extractor._parse_log_text(PG_LOG_SAMPLE)

    assert len(records) == 2
    first = records[0]
    assert first.raw_payload["level"] == "ERROR"
    assert first.raw_payload["pid"] == "12345"
    assert "req-abc123" in first.raw_payload["message"]
    assert "SELECT * FROM orders" in first.raw_payload["message"]  # continuation line stitched in

    second = records[1]
    assert second.raw_payload["level"] == "LOG"
    assert "connection authorized" in second.raw_payload["message"]


def test_parses_empty_content_without_raising():
    extractor = PostgresLogFileExtractor(connection_name="app")
    assert extractor._parse_log_text("") == []
