package com.example;

import java.util.logging.Level;
import java.util.logging.Logger;

class OrderService {

    private static final Logger LOGGER = Logger.getLogger(OrderService.class.getName());

    static final String COMPONENT_ID = "orders-service";
    static final String DEFAULT_APPLICATION_NAME = "tomcat-log-source";

    String retrieveOrder(RequestContext ctx, String orderId) {
        LOGGER.info(head(ctx) + "order retrieved order_id=" + orderId + tail(ctx));
        return orderId;
    }

    String createOrder(RequestContext ctx, String sku) {
        String orderId = "ord-" + Integer.toHexString(sku.hashCode() & 0xffffff);
        LOGGER.info(head(ctx) + "order created order_id=" + orderId + " sku=" + sku + tail(ctx));
        return orderId;
    }

    // Deliberately undguarded: the null catalog entry surfaces as a real NPE
    // with a genuine multi-frame stack trace, not a manually thrown one.
    void lookupWithBrokenCatalog(String trxId) {
        OrderCatalogEntry entry = fetchCatalogEntry(trxId);
        entry.describe();
    }

    private OrderCatalogEntry fetchCatalogEntry(String trxId) {
        return null;
    }

    void reportDbFailure(RequestContext ctx, String orderId) {
        LOGGER.log(Level.SEVERE, head(ctx)
                + "DB connection failed for order lookup order_id=" + orderId
                + (ctx.identifierFree() ? "" : " error_code=DB_TIMEOUT") + tail(ctx));
    }

    // Every identity-bearing prefix funnels through here instead of being
    // inlined at each call site, so identifierFree has exactly one place to
    // gate (postgres-scenario-harness). Replaces the formerly hard-coded
    // "request_id=" + trxId + " " prefix.
    static String head(RequestContext ctx) {
        return ctx.identifierFree() ? "" : "request_id=" + ctx.trxId() + " ";
    }

    // Duplicates each identifier under both the friendly MDC-style names and
    // the canonical names normalization/normalizer.py's regex already
    // matches (trace_id/user_id/service_name) — mirrors the CloudWatch log
    // generator's format so the same trxId is findable via either
    // vocabulary, with zero changes needed on the Python side. Suppressed
    // entirely in identifierFree mode — including the friendly names, since
    // an identical trxId on two lines is a free giveaway to the semantic
    // LLM stage even though it matches no CORRELATION_KEY_PATTERNS regex.
    static String tail(RequestContext ctx) {
        if (ctx.identifierFree()) {
            return "";
        }
        return " trxId=" + ctx.trxId()
                + " username=" + ctx.username()
                + " componentId=" + ctx.componentId()
                + " applicationName=" + ctx.applicationName()
                + " correlated=" + ctx.correlated()
                + " trace_id=" + ctx.trxId()
                + " user_id=" + ctx.username()
                + " service_name=" + ctx.componentId();
    }

    private static final class OrderCatalogEntry {
        void describe() {
            // never reached; lookupWithBrokenCatalog() NPEs before this point
        }
    }
}
