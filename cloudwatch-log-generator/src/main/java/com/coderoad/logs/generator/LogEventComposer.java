package com.coderoad.logs.generator;

/**
 * Builds the final human-readable log message text for one generated event.
 *
 * <p>The primary fields the app was asked to produce (trxId, username,
 * componentId) are always included verbatim as {@code key=value} tokens.
 * When {@code emitCorrelationAliases} is enabled, a second set of tokens
 * using the identifier names the companion {@code log_correlation_poc}
 * project's regex-based extractor already recognizes
 * ({@code trace_id}, {@code request_id}, {@code user_id}, {@code service_name},
 * {@code error_code}) is appended, so a single generated log line is
 * consumable both on its own terms and as test input for that pipeline.
 *
 * <p>Kept as a pure function (no logging/CDI) so message shape is unit
 * testable without a running Quarkus context.
 */
public final class LogEventComposer {

    private LogEventComposer() {
    }

    public static String compose(String baseMessage,
                                  String trxId,
                                  String username,
                                  String componentId,
                                  String errorCode,
                                  boolean emitCorrelationAliases,
                                  boolean identifierFree) {
        // identifierFree (postgres-scenario-harness): only the human
        // narrative remains — no trxId/username/componentId, no errorCode=
        // (case-insensitive regex match, so lower-casing it would not be
        // enough), and it forces the alias block off regardless of what
        // emitCorrelationAliases requested.
        if (identifierFree) {
            return baseMessage;
        }

        StringBuilder message = new StringBuilder(baseMessage)
                .append(" | trxId=").append(trxId)
                .append(" username=").append(username)
                .append(" componentId=").append(componentId);

        if (errorCode != null) {
            message.append(" errorCode=").append(errorCode);
        }

        if (emitCorrelationAliases) {
            String trxAlias = RandomLogValues.sanitizeForAlias(trxId, false);
            String usernameAlias = RandomLogValues.sanitizeForAlias(username, false);
            String componentAlias = RandomLogValues.sanitizeForAlias(componentId, true);

            message.append(" trace_id=").append(trxAlias)
                    .append(" request_id=").append(trxAlias)
                    .append(" user_id=").append(usernameAlias)
                    .append(" service_name=").append(componentAlias);

            if (errorCode != null) {
                message.append(" error_code=").append(errorCode);
            }
        }

        return message.toString();
    }
}
