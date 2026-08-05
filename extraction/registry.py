"""
Builds the list of active extractors from config. CloudWatch is always
considered first/primary; other sources only activate if their *_ENABLED
flag is set, so the POC can run against CloudWatch alone (business case
slide 10 stage 1) without deleting or commenting out code for the rest
of the architecture.
"""
from __future__ import annotations

import logging
from typing import List

import config
from extraction.base import BaseExtractor
from extraction.cloudwatch_extractor import CloudWatchExtractor
from extraction.tomcat_extractor import TomcatExtractor
from extraction.gcp_logging_extractor import GCPLoggingExtractor
from extraction.db_log_extractor import DBLogSourceConfig, build_db_extractor

logger = logging.getLogger(__name__)


def build_extractors() -> List[BaseExtractor]:
    extractors: List[BaseExtractor] = []

    if config.CLOUDWATCH_ENABLED:
        extractors.append(CloudWatchExtractor())
    else:
        logger.info("CloudWatch extraction disabled via config")

    if config.TOMCAT_ENABLED:
        extractors.append(TomcatExtractor())

    if config.GCP_LOGGING_ENABLED:
        extractors.append(GCPLoggingExtractor())

    if config.DB_LOGS_ENABLED:
        for source in config.DB_LOG_SOURCES:
            engine, _, connection_name = source.partition(":")
            if engine and connection_name:
                extractors.append(build_db_extractor(DBLogSourceConfig(engine=engine, connection_name=connection_name)))
            else:
                logger.warning("Skipping malformed DB_LOG_SOURCES entry: %r (expected 'engine:connection_name')", source)

    if not extractors:
        raise RuntimeError(
            "No extractors enabled. Set CLOUDWATCH_ENABLED=true (or another "
            "*_ENABLED flag) in your .env."
        )

    logger.info("Active extractors: %s", extractors)
    return extractors
