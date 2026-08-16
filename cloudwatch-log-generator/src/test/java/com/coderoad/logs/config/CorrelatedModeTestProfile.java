package com.coderoad.logs.config;

import java.util.Map;

import io.quarkus.test.junit.QuarkusTestProfile;

public class CorrelatedModeTestProfile implements QuarkusTestProfile {

    @Override
    public Map<String, String> getConfigOverrides() {
        return Map.of(
                "generateCorrelatedLogs", "true",
                "trxId", "11111111-1111-4111-8111-111111111111",
                "username", "qa-user-001",
                "componentId", "qa-test-service"
        );
    }
}
