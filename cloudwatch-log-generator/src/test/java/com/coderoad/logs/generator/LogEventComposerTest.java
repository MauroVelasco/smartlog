package com.coderoad.logs.generator;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class LogEventComposerTest {

    @Test
    void alwaysIncludesTheThreeCorePrimarySpecFields() {
        String message = LogEventComposer.compose(
                "Order created", "trx-12345678", "jdoe-100", "order-service", null, false, false);

        assertTrue(message.contains("trxId=trx-12345678"));
        assertTrue(message.contains("username=jdoe-100"));
        assertTrue(message.contains("componentId=order-service"));
    }

    @Test
    void omitsPocAliasesWhenDisabled() {
        String message = LogEventComposer.compose(
                "Order created", "trx-12345678", "jdoe-100", "order-service", null, false, false);

        assertFalse(message.contains("trace_id="));
        assertFalse(message.contains("request_id="));
        assertFalse(message.contains("user_id="));
        assertFalse(message.contains("service_name="));
    }

    @Test
    void includesPocCompatibleAliasesMatchingItsExtractionRegexesWhenEnabled() {
        String message = LogEventComposer.compose(
                "Payment gateway timeout", "trx-12345678", "jdoe-100", "order-service", "ERR-5000", true, false);

        assertTrue(message.matches("(?s).*\\btrace_id=[a-zA-Z0-9\\-]{8,}\\b.*"), message);
        assertTrue(message.matches("(?s).*\\brequest_id=[a-zA-Z0-9\\-]{8,}\\b.*"), message);
        assertTrue(message.matches("(?s).*\\buser_id=[a-zA-Z0-9\\-]{3,}\\b.*"), message);
        assertTrue(message.matches("(?s).*\\bservice_name=[a-zA-Z0-9\\-_.]{2,}\\b.*"), message);
        assertTrue(message.contains("error_code=ERR-5000"));
    }

    @Test
    void omitsErrorCodeTokensWhenLevelHasNoErrorCode() {
        String message = LogEventComposer.compose(
                "Health check passed", "trx-12345678", "jdoe-100", "order-service", null, true, false);

        assertFalse(message.contains("errorCode="));
        assertFalse(message.contains("error_code="));
    }

    // --- identifierFree (postgres-scenario-harness) ---

    @Test
    void identifierFreeReturnsOnlyTheBaseMessage() {
        String message = LogEventComposer.compose(
                "Payment gateway timeout", "trx-12345678", "jdoe-100", "order-service", "ERR-5000", false, true);

        assertEquals("Payment gateway timeout", message);
    }

    @Test
    void identifierFreeForcesAliasesOffEvenWhenRequested() {
        String message = LogEventComposer.compose(
                "Payment gateway timeout", "trx-12345678", "jdoe-100", "order-service", "ERR-5000", true, true);

        // emitCorrelationAliases=true is explicitly requested here, but
        // identifierFree must win — no alias tokens, no primary tokens,
        // no errorCode= at all (case-insensitive check: the regex match is
        // case-insensitive, so a merely-lowercased errorcode would still leak).
        assertEquals("Payment gateway timeout", message);
        assertFalse(message.toLowerCase().contains("errorcode"));
    }
}
