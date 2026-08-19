package com.coderoad.logs.generator;

import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;

import org.junit.jupiter.api.RepeatedTest;
import org.junit.jupiter.api.Test;

class RandomLogValuesTest {

    @RepeatedTest(20)
    void trxIdMatchesTraceIdAndRequestIdCharset() {
        assertTrue(RandomLogValues.randomTrxId().matches("[a-zA-Z0-9\\-]{8,}"));
    }

    @RepeatedTest(20)
    void usernameMatchesUserIdCharset() {
        assertTrue(RandomLogValues.randomUsername().matches("[a-zA-Z0-9\\-]{3,}"));
    }

    @RepeatedTest(20)
    void componentIdMatchesServiceNameCharset() {
        assertTrue(RandomLogValues.randomComponentId().matches("[a-zA-Z0-9\\-_.]{2,}"));
    }

    @RepeatedTest(20)
    void errorCodeMatchesErrorCodeCharset() {
        assertTrue(RandomLogValues.randomErrorCode().matches("[A-Z0-9_\\-]{2,}"));
    }

    @RepeatedTest(50)
    void levelIsAlwaysOneOfTheFourKnownLevels() {
        assertTrue(List.of("INFO", "WARN", "ERROR", "DEBUG").contains(RandomLogValues.randomLevel()));
    }

    @Test
    void randomMessageFallsBackToInfoPoolForUnknownLevel() {
        assertTrue(!RandomLogValues.randomMessage("NOT_A_LEVEL").isBlank());
    }

    @Test
    void sanitizeForAliasStripsDisallowedCharactersAndPadsShortValues() {
        String sanitized = RandomLogValues.sanitizeForAlias("ab_c!", false);
        assertTrue(sanitized.matches("[a-zA-Z0-9\\-]{8,}"), sanitized);
    }

    @Test
    void sanitizeForAliasAllowsDotAndUnderscoreWhenRequested() {
        String sanitized = RandomLogValues.sanitizeForAlias("order.service_v2", true);
        assertTrue(sanitized.matches("[a-zA-Z0-9\\-_.]{2,}"), sanitized);
    }

    @Test
    void sanitizeForAliasHandlesNull() {
        String sanitized = RandomLogValues.sanitizeForAlias(null, false);
        assertTrue(sanitized.matches("[a-zA-Z0-9\\-]{8,}"), sanitized);
    }

    // --- randomException ---

    @Test
    void randomExceptionSometimesReturnsNullAndSometimesDoesNot() {
        boolean sawNull = false;
        boolean sawNonNull = false;
        for (int i = 0; i < 200 && !(sawNull && sawNonNull); i++) {
            Throwable exception = RandomLogValues.randomException("ERR-5000", "Unhandled exception while processing request");
            if (exception == null) {
                sawNull = true;
            } else {
                sawNonNull = true;
            }
        }
        assertTrue(sawNull, "expected at least one null result across 200 attempts");
        assertTrue(sawNonNull, "expected at least one non-null result across 200 attempts");
    }

    @RepeatedTest(30)
    void randomExceptionMessageMatchesTheGivenBaseMessageWhenPresent() {
        Throwable exception = RandomLogValues.randomException("ERR-5000", "Unhandled exception while processing request");
        if (exception != null) {
            assertTrue("Unhandled exception while processing request".equals(exception.getMessage()));
        }
    }

    @RepeatedTest(30)
    void randomExceptionForDbConnErrorCodeIsSqlFlavored() {
        Throwable exception = RandomLogValues.randomException("DB-CONN-01", "Database transaction rolled back");
        if (exception != null) {
            assertTrue(exception instanceof java.sql.SQLException, exception.getClass().getName());
        }
    }

    @RepeatedTest(30)
    void randomExceptionForTimeoutErrorCodeIsTimeoutFlavored() {
        Throwable exception = RandomLogValues.randomException("TIMEOUT-001", "Payment gateway timeout");
        if (exception != null) {
            assertTrue(
                    exception instanceof java.util.concurrent.TimeoutException
                            || exception instanceof java.net.SocketTimeoutException,
                    exception.getClass().getName());
        }
    }

    @Test
    void randomExceptionForUnknownErrorCodeFallsBackToGenericPoolWithoutThrowing() {
        Throwable exception = RandomLogValues.randomException("SOME-UNMAPPED-CODE", "Something went wrong");
        if (exception != null) {
            assertTrue("Something went wrong".equals(exception.getMessage()));
        }
    }

    @Test
    void randomExceptionEventuallyProducesAChainedCause() {
        boolean sawCause = false;
        for (int i = 0; i < 200 && !sawCause; i++) {
            Throwable exception = RandomLogValues.randomException("ERR-5000", "Unhandled exception while processing request");
            if (exception != null && exception.getCause() != null) {
                sawCause = true;
            }
        }
        assertTrue(sawCause, "expected at least one chained cause across 200 attempts");
    }
}
