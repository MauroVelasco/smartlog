from extraction.gcp_logging_extractor import GCPLoggingExtractor


def test_flatten_text_payload():
    message, payload_type = GCPLoggingExtractor._flatten_payload("plain text log line")
    assert message == "plain text log line"
    assert payload_type == "text"


def test_flatten_json_payload_with_message_key():
    message, payload_type = GCPLoggingExtractor._flatten_payload(
        {"message": "request_id=req-1 timeout", "severity": "ERROR"}
    )
    assert payload_type == "json"
    assert message.startswith("request_id=req-1 timeout")
    assert '"severity": "ERROR"' in message


def test_flatten_json_payload_without_message_key_falls_back_to_full_json():
    message, payload_type = GCPLoggingExtractor._flatten_payload({"foo": "bar"})
    assert payload_type == "json"
    assert '"foo": "bar"' in message


def test_flatten_empty_payload():
    message, payload_type = GCPLoggingExtractor._flatten_payload(None)
    assert message == ""
    assert payload_type == "empty"
