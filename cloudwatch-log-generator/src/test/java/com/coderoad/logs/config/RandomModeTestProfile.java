package com.coderoad.logs.config;

import java.util.Map;

import io.quarkus.test.junit.QuarkusTestProfile;

public class RandomModeTestProfile implements QuarkusTestProfile {

    @Override
    public Map<String, String> getConfigOverrides() {
        return Map.of("generateCorrelatedLogs", "false");
    }
}
