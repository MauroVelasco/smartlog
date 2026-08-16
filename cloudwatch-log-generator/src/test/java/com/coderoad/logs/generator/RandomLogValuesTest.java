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
}
