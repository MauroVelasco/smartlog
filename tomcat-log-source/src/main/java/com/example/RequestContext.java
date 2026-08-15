package com.example;

import jakarta.servlet.http.HttpServletRequest;

// Every field is overridable via query param so an external demo
// orchestrator can feed the same trxId/username/componentId into both this
// app and the team's CloudWatch log generator, producing genuinely
// cross-source-correlatable events instead of two independently random ones.
record RequestContext(String trxId, String username, String componentId, String applicationName, boolean correlated) {

    static RequestContext fromRequest(HttpServletRequest req) {
        return new RequestContext(
                param(req, "trxId", RequestIds.next()),
                param(req, "username", Users.next()),
                param(req, "componentId", OrderService.COMPONENT_ID),
                param(req, "applicationName", OrderService.DEFAULT_APPLICATION_NAME),
                Boolean.parseBoolean(param(req, "correlated", "false")));
    }

    private static String param(HttpServletRequest req, String name, String fallback) {
        String value = req.getParameter(name);
        return (value == null || value.isBlank()) ? fallback : value;
    }
}
