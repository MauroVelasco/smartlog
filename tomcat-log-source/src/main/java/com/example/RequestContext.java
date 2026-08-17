package com.example;

import jakarta.servlet.http.HttpServletRequest;

// Every field is overridable via query param so an external demo
// orchestrator can feed the same trxId/username/componentId into both this
// app and the team's CloudWatch log generator, producing genuinely
// cross-source-correlatable events instead of two independently random ones.
//
// identifierFree (postgres-scenario-harness): when true, suppresses every
// identity token from the emitted log text — both the regex-matchable names
// (request_id/trace_id/user_id/service_name/error_code) and the friendly
// ones (trxId/username/componentId/applicationName/correlated). Default
// false preserves today's behavior exactly (Tier 1 regression guard).
record RequestContext(
        String trxId, String username, String componentId, String applicationName, boolean correlated,
        boolean identifierFree) {

    static RequestContext fromRequest(HttpServletRequest req) {
        return new RequestContext(
                param(req, "trxId", RequestIds.next()),
                param(req, "username", Users.next()),
                param(req, "componentId", OrderService.COMPONENT_ID),
                param(req, "applicationName", OrderService.DEFAULT_APPLICATION_NAME),
                Boolean.parseBoolean(param(req, "correlated", "false")),
                Boolean.parseBoolean(param(req, "identifierFree", "false")));
    }

    private static String param(HttpServletRequest req, String name, String fallback) {
        String value = req.getParameter(name);
        return (value == null || value.isBlank()) ? fallback : value;
    }
}
