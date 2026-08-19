package com.coderoad.logs.generator;

import com.coderoad.logs.config.CorrelationConfig;

import io.quarkus.scheduler.Scheduled;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.jboss.logging.Logger;
import org.jboss.logging.MDC;

/**
 * Periodically emits one (or a configurable batch of) synthetic log line(s).
 *
 * <p>Each event is logged through JBoss Logging, which quarkus-logging-json
 * renders as a single JSON object on stdout. In ECS, the container's
 * {@code awslogs} log driver ships that stdout line to CloudWatch Logs as-is
 * - this app never talks to the CloudWatch API directly, it just logs like
 * any well-behaved container workload.
 */
@ApplicationScoped
public class LogGeneratorScheduler {

    private static final Logger LOG = Logger.getLogger("cloudwatch-log-generator");

    @Inject
    CorrelationConfig correlationConfig;

    @ConfigProperty(name = "log.generator.application-name", defaultValue = "cloudwatch-log-generator")
    String applicationName;

    @ConfigProperty(name = "log.generator.batch-size", defaultValue = "1")
    int batchSize;

    @ConfigProperty(name = "log.generator.emit-correlation-aliases", defaultValue = "true")
    boolean emitCorrelationAliases;

    @Scheduled(every = "{log.generator.interval}")
    void generate() {
        int count = Math.max(1, batchSize);
        for (int i = 0; i < count; i++) {
            emitOne();
        }
    }

    private void emitOne() {
        LOG.infof("Emitting one log event");
        boolean correlated = correlationConfig.isCorrelatedMode();
        String trxId = correlationConfig.trxId();
        String username = correlationConfig.username();
        String componentId = correlationConfig.componentId();

        String level = RandomLogValues.randomLevel();
        String baseMessage = RandomLogValues.randomMessage(level);
        String errorCode = isWarnOrError(level) ? RandomLogValues.randomErrorCode() : null;

        // Only ERROR events get a synthetic exception/stack trace attached -
        // WARN/INFO/DEBUG stay plain text, matching how real applications
        // typically only log a full Throwable at ERROR severity.
        Throwable exception = "ERROR".equals(level) ? RandomLogValues.randomException(errorCode, baseMessage) : null;

        boolean identifierFree = correlationConfig.isIdentifierFree();
        String message = LogEventComposer.compose(
                baseMessage, trxId, username, componentId, errorCode, emitCorrelationAliases, identifierFree);

        // MDC fields are rendered by quarkus-logging-json under the "mdc" key
        // of every JSON log record, giving trxId/username/componentId as
        // first-class, queryable fields in CloudWatch Logs Insights - not
        // just embedded text.
        MDC.put("trxId", trxId);
        MDC.put("username", username);
        MDC.put("componentId", componentId);
        MDC.put("correlated", String.valueOf(correlated));
        MDC.put("applicationName", applicationName);
        if (errorCode != null) {
            MDC.put("errorCode", errorCode);
        }
        if (exception != null) {
            MDC.put("exceptionType", exception.getClass().getName());
        }
        try {
            log(level, message, exception);
        } finally {
            MDC.clear();
        }
    }

    private static boolean isWarnOrError(String level) {
        return "WARN".equals(level) || "ERROR".equals(level);
    }

    private void log(String level, String message, Throwable exception) {
        switch (level) {
            case "ERROR" -> {
                if (exception != null) {
                    // quarkus-logging-json (see determine-print-stack-trace-by-throwable /
                    // exception-output-type in application.properties) renders this
                    // Throwable's full stack trace, chained causes included.
                    LOG.error(message, exception);
                } else {
                    LOG.error(message);
                }
            }
            case "WARN" -> LOG.warn(message);
            case "DEBUG" -> LOG.debug(message);
            default -> LOG.info(message);
        }
    }
}
