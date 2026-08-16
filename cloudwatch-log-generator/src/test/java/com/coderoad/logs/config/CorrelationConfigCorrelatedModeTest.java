package com.coderoad.logs.config;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import jakarta.inject.Inject;

import org.junit.jupiter.api.Test;

import io.quarkus.test.junit.QuarkusTest;
import io.quarkus.test.junit.TestProfile;

@QuarkusTest
@TestProfile(CorrelatedModeTestProfile.class)
class CorrelationConfigCorrelatedModeTest {

    @Inject
    CorrelationConfig config;

    @Test
    void reusesTheConfiguredValuesOnEveryCall() {
        assertTrue(config.isCorrelatedMode());

        assertEquals("11111111-1111-4111-8111-111111111111", config.trxId());
        assertEquals("11111111-1111-4111-8111-111111111111", config.trxId());

        assertEquals("qa-user-001", config.username());
        assertEquals("qa-test-service", config.componentId());
    }
}
