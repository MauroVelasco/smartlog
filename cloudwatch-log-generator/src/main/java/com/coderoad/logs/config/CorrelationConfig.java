package com.coderoad.logs.config;

import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Supplier;

import com.coderoad.logs.generator.RandomLogValues;

import jakarta.enterprise.context.ApplicationScoped;
import org.eclipse.microprofile.config.inject.ConfigProperty;

/**
 * Resolves trxId/username/componentId according to the
 * {@code generateCorrelatedLogs} environment variable.
 *
 * <ul>
 *   <li><b>{@code generateCorrelatedLogs=true}</b>: every generated log
 *       event reuses the value of the matching environment variable
 *       ({@code trxId}, {@code username}, {@code componentId}). If one of
 *       those was left unset, a single random value is generated the first
 *       time it's needed and cached for the rest of the process's lifetime,
 *       so the run still stays internally correlated even with an
 *       incomplete configuration.</li>
 *   <li><b>{@code generateCorrelatedLogs=false}</b> (default): a brand-new
 *       random value is produced for every single log event, regardless of
 *       what (if anything) was configured.</li>
 * </ul>
 *
 * <p>The property names below are intentionally exact matches for the
 * environment variable names ({@code generateCorrelatedLogs}, {@code trxId},
 * {@code username}, {@code componentId}) - MicroProfile Config tries an
 * exact-name env var lookup before falling back to the usual
 * upper-snake-case conversion, so these can be set literally in the ECS task
 * definition's container environment variables.
 */
@ApplicationScoped
public class CorrelationConfig {

    @ConfigProperty(name = "generateCorrelatedLogs", defaultValue = "false")
    boolean generateCorrelatedLogs;

    @ConfigProperty(name = "trxId")
    Optional<String> configuredTrxId;

    @ConfigProperty(name = "username")
    Optional<String> configuredUsername;

    @ConfigProperty(name = "componentId")
    Optional<String> configuredComponentId;

    private final AtomicReference<String> fallbackTrxId = new AtomicReference<>();
    private final AtomicReference<String> fallbackUsername = new AtomicReference<>();
    private final AtomicReference<String> fallbackComponentId = new AtomicReference<>();

    public boolean isCorrelatedMode() {
        return generateCorrelatedLogs;
    }

    public String trxId() {
        return generateCorrelatedLogs
                ? resolve(configuredTrxId, fallbackTrxId, RandomLogValues::randomTrxId)
                : RandomLogValues.randomTrxId();
    }

    public String username() {
        return generateCorrelatedLogs
                ? resolve(configuredUsername, fallbackUsername, RandomLogValues::randomUsername)
                : RandomLogValues.randomUsername();
    }

    public String componentId() {
        return generateCorrelatedLogs
                ? resolve(configuredComponentId, fallbackComponentId, RandomLogValues::randomComponentId)
                : RandomLogValues.randomComponentId();
    }

    private static String resolve(Optional<String> configured, AtomicReference<String> cache, Supplier<String> randomSupplier) {
        if (configured.isPresent() && !configured.get().isBlank()) {
            return configured.get();
        }
        return cache.updateAndGet(current -> current != null ? current : randomSupplier.get());
    }
}
