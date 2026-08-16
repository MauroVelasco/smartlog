package com.coderoad.logs.config;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import jakarta.inject.Inject;

import org.junit.jupiter.api.Test;

import io.quarkus.test.junit.QuarkusTest;
import io.quarkus.test.junit.TestProfile;

@QuarkusTest
@TestProfile(CorrelatedFallbackTestProfile.class)
class CorrelationConfigFallbackTest {

    @Inject
    CorrelationConfig config;

    @Test
    void generatesAndCachesAValueWhenCorrelatedButUnconfigured() {
        assertTrue(config.isCorrelatedMode());

        String firstTrxId = config.trxId();
        assertEquals(firstTrxId, config.trxId());

        assertNotNull(config.username());
        assertNotNull(config.componentId());
    }
}
