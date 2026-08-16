package com.coderoad.logs.config;

import java.util.Map;

import io.quarkus.test.junit.QuarkusTestProfile;

/** generateCorrelatedLogs=true but trxId/username/componentId left unset. */
public class CorrelatedFallbackTestProfile implements QuarkusTestProfile {

    @Override
    public Map<String, String> getConfigOverrides() {
        return Map.of("generateCorrelatedLogs", "true");
    }
}
