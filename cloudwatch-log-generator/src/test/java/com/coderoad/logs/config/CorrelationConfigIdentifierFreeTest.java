package com.coderoad.logs.config;

import static org.junit.jupiter.api.Assertions.assertTrue;

import jakarta.inject.Inject;

import org.junit.jupiter.api.Test;

import io.quarkus.test.junit.QuarkusTest;
import io.quarkus.test.junit.TestProfile;

@QuarkusTest
@TestProfile(IdentifierFreeTestProfile.class)
class CorrelationConfigIdentifierFreeTest {

    @Inject
    CorrelationConfig config;

    @Test
    void reportsIdentifierFreeWhenEnvVarIsSet() {
        assertTrue(config.isIdentifierFree());
    }
}
