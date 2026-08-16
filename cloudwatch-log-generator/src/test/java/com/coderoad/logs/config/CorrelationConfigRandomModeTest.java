package com.coderoad.logs.config;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;

import jakarta.inject.Inject;

import org.junit.jupiter.api.Test;

import io.quarkus.test.junit.QuarkusTest;
import io.quarkus.test.junit.TestProfile;

@QuarkusTest
@TestProfile(RandomModeTestProfile.class)
class CorrelationConfigRandomModeTest {

    @Inject
    CorrelationConfig config;

    @Test
    void producesADifferentTrxIdOnEveryCall() {
        assertFalse(config.isCorrelatedMode());
        assertNotEquals(config.trxId(), config.trxId());
    }
}
