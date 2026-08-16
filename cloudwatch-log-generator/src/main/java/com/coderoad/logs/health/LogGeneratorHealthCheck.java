package com.coderoad.logs.health;

import jakarta.enterprise.context.ApplicationScoped;
import org.eclipse.microprofile.health.HealthCheck;
import org.eclipse.microprofile.health.HealthCheckResponse;
import org.eclipse.microprofile.health.Liveness;
import org.eclipse.microprofile.health.Readiness;

/**
 * Trivial liveness/readiness check exposed at {@code /q/health},
 * {@code /q/health/live} and {@code /q/health/ready}. This is a background
 * job with no external dependencies, so "the process is up" is sufficient -
 * wire this into the ECS task definition's container {@code healthCheck}.
 */
@ApplicationScoped
@Liveness
@Readiness
public class LogGeneratorHealthCheck implements HealthCheck {

    @Override
    public HealthCheckResponse call() {
        return HealthCheckResponse.named("cloudwatch-log-generator").up().build();
    }
}
