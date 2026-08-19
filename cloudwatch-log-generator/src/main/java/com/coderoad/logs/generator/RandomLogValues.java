package com.coderoad.logs.generator;

import java.security.SecureRandom;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Function;

/**
 * Pure, side-effect-free generators for random log content. Kept free of any
 * CDI/Quarkus dependency so it can be unit tested directly.
 *
 * <p>Value shapes are deliberately constrained to the character sets the
 * companion {@code log_correlation_poc} project's extraction regexes expect
 * (see {@code RandomLogValues#sanitizeForAlias} and the README), so output
 * from this generator can be fed straight into that pipeline for testing:
 * <ul>
 *   <li>{@code trace_id} / {@code request_id}: {@code [a-zA-Z0-9-]{8,}}</li>
 *   <li>{@code user_id}: {@code [a-zA-Z0-9-]{3,}}</li>
 *   <li>{@code service_name}: {@code [a-zA-Z0-9-_.]{2,}}</li>
 *   <li>{@code error_code}: {@code [A-Z0-9_-]{2,}}</li>
 * </ul>
 */
public final class RandomLogValues {

    private static final SecureRandom RANDOM = new SecureRandom();

    private static final List<String> USERNAME_STEMS = List.of(
            "jsmith", "mgarcia", "achen", "rpatel", "lwong", "kjones", "dnguyen",
            "tortiz", "fmuller", "svargas", "hkim", "aolawale", "bcosta", "nyilmaz"
    );

    private static final List<String> COMPONENT_IDS = List.of(
            "order-service", "payment-service", "inventory-service", "auth-service",
            "notification-service", "shipping-service", "catalog-service", "user-service",
            "billing-service", "gateway-service"
    );

    private static final List<String> ERROR_CODES = List.of(
            "ERR-4001", "ERR-4030", "ERR-5000", "ERR-5030", "TIMEOUT-001",
            "AUTH-403", "DB-CONN-01", "VALIDATION-422", "RATE-LIMIT-429", "DEP-UNAVAILABLE"
    );

    private static final Map<String, List<String>> MESSAGES_BY_LEVEL = Map.of(
            "INFO", List.of(
                    "Request processed successfully",
                    "Health check passed",
                    "Cache warmed for key set",
                    "Scheduled job completed",
                    "User session established",
                    "Order created successfully",
                    "Payment authorized",
                    "Inventory levels synced",
                    "Configuration reloaded",
                    "Outbound webhook delivered"
            ),
            "WARN", List.of(
                    "Retrying operation after transient failure",
                    "Response time exceeded threshold",
                    "Deprecated API endpoint invoked",
                    "Connection pool nearing capacity",
                    "Cache miss rate elevated",
                    "Rate limit threshold approaching",
                    "Non-critical dependency slow to respond",
                    "Stale configuration detected, using cached value"
            ),
            "ERROR", List.of(
                    "Failed to connect to downstream service",
                    "Unhandled exception while processing request",
                    "Database transaction rolled back",
                    "Authentication token validation failed",
                    "Payment gateway timeout",
                    "Message queue publish failed",
                    "Circuit breaker opened for dependency",
                    "Data validation failed, request rejected"
            ),
            "DEBUG", List.of(
                    "Entering method processRequest",
                    "Cache lookup result computed",
                    "Evaluating feature flag",
                    "Serializing response payload",
                    "Dispatching event to listener"
            )
    );

    /**
     * Per-error-code exception "flavor" pools, so a stack trace attached to a
     * {@code DB-CONN-01} event looks like a JDBC failure, a
     * {@code TIMEOUT-001} event looks like a network timeout, and so on,
     * rather than an arbitrary unrelated exception type. Any error code not
     * listed here falls back to {@link #GENERIC_EXCEPTION_FACTORIES}.
     */
    private static final Map<String, List<Function<String, Throwable>>> EXCEPTION_FACTORIES_BY_ERROR_CODE = Map.of(
            "DB-CONN-01", List.of(
                    message -> new java.sql.SQLException(message, "08001"),
                    message -> new java.sql.SQLTransientException(message)
            ),
            "TIMEOUT-001", List.of(
                    message -> new java.util.concurrent.TimeoutException(message),
                    message -> new java.net.SocketTimeoutException(message)
            ),
            "AUTH-403", List.of(
                    message -> new SecurityException(message)
            ),
            "VALIDATION-422", List.of(
                    message -> new IllegalArgumentException(message)
            ),
            "RATE-LIMIT-429", List.of(
                    message -> new java.util.concurrent.RejectedExecutionException(message)
            ),
            "DEP-UNAVAILABLE", List.of(
                    message -> new java.io.IOException(message),
                    message -> new java.net.ConnectException(message)
            ),
            "ERR-5030", List.of(
                    message -> new java.io.IOException(message)
            )
    );

    /** Fallback pool for error codes ({@code ERR-4001}, {@code ERR-4030}, {@code ERR-5000}) with no specific flavor mapping above. */
    private static final List<Function<String, Throwable>> GENERIC_EXCEPTION_FACTORIES = List.of(
            RuntimeException::new,
            IllegalStateException::new,
            NullPointerException::new,
            java.util.NoSuchElementException::new
    );

    /** Short, low-level failure descriptions used for the chained "Caused by:" exception. */
    private static final List<String> EXCEPTION_CAUSE_MESSAGES = List.of(
            "Connection reset by peer",
            "Read timed out",
            "Connection refused",
            "Unexpected end of stream",
            "Broken pipe",
            "No route to host"
    );

    private RandomLogValues() {
    }

    /** Matches [a-zA-Z0-9-]{8,} - safe for trxId and, verbatim, for the trace_id/request_id aliases. */
    public static String randomTrxId() {
        return UUID.randomUUID().toString();
    }

    /** Matches [a-zA-Z0-9-]{3,} - safe for username and, verbatim, for the user_id alias. */
    public static String randomUsername() {
        String stem = pick(USERNAME_STEMS);
        int suffix = 100 + RANDOM.nextInt(900);
        return stem + "-" + suffix;
    }

    /** Matches [a-zA-Z0-9-_.]{2,} - safe for componentId and, verbatim, for the service_name alias. */
    public static String randomComponentId() {
        return pick(COMPONENT_IDS);
    }

    /** Matches [A-Z0-9_-]{2,} - used for the error_code alias on WARN/ERROR events. */
    public static String randomErrorCode() {
        return pick(ERROR_CODES);
    }

    /** Weighted so the stream of logs looks like real traffic: INFO 65%, WARN 20%, ERROR 10%, DEBUG 5%. */
    public static String randomLevel() {
        int roll = RANDOM.nextInt(100);
        if (roll < 65) {
            return "INFO";
        }
        if (roll < 85) {
            return "WARN";
        }
        if (roll < 95) {
            return "ERROR";
        }
        return "DEBUG";
    }

    public static String randomMessage(String level) {
        List<String> pool = MESSAGES_BY_LEVEL.getOrDefault(level, MESSAGES_BY_LEVEL.get("INFO"));
        return pick(pool);
    }

    /**
     * Builds a synthetic exception to attach to an ERROR-level event, chosen
     * from a pool that roughly matches the given error code's flavor (a
     * {@code DB-CONN-01} error looks like a JDBC failure, {@code TIMEOUT-001}
     * like a network timeout, etc.) so the stack trace CloudWatch receives
     * looks like it could plausibly have produced the accompanying message.
     *
     * <p>Returns {@code null} about a quarter of the time - not every ERROR
     * event in a real system was triggered by a caught exception (some are
     * plain business-rule failures), so callers should treat a {@code null}
     * result as "log this ERROR without a stack trace". About a third of the
     * non-null results also get a chained "Caused by:" exception, since real
     * production stack traces are very often wrapped.
     */
    public static Throwable randomException(String errorCode, String baseMessage) {
        if (RANDOM.nextInt(4) == 0) {
            return null;
        }
        List<Function<String, Throwable>> pool =
                EXCEPTION_FACTORIES_BY_ERROR_CODE.getOrDefault(errorCode, GENERIC_EXCEPTION_FACTORIES);
        Throwable exception = pick(pool).apply(baseMessage);

        if (RANDOM.nextInt(3) == 0) {
            Throwable cause = pick(GENERIC_EXCEPTION_FACTORIES).apply(pick(EXCEPTION_CAUSE_MESSAGES));
            exception.initCause(cause);
        }
        return exception;
    }

    /**
     * Reduces an arbitrary configured value (trxId/username/componentId, which
     * are emitted verbatim everywhere else) down to the character set the
     * log_correlation_poc extraction regexes require, so the compatibility
     * alias tokens (trace_id=/request_id=/user_id=/service_name=) always
     * parse even if an operator configured a value containing characters
     * those regexes don't allow (e.g. underscores or spaces in trxId).
     */
    public static String sanitizeForAlias(String value, boolean allowDotUnderscore) {
        String source = value == null ? "" : value;
        String disallowedCharsPattern = allowDotUnderscore ? "[^a-zA-Z0-9\\-_.]" : "[^a-zA-Z0-9\\-]";
        String cleaned = source.replaceAll(disallowedCharsPattern, "-");
        StringBuilder padded = new StringBuilder(cleaned);
        while (padded.length() < 8) {
            padded.append('0');
        }
        return padded.toString();
    }

    private static <T> T pick(List<T> pool) {
        return pool.get(RANDOM.nextInt(pool.size()));
    }
}
