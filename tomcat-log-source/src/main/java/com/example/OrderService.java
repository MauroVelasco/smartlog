package com.example;

import java.util.logging.Level;
import java.util.logging.Logger;

class OrderService {

    private static final Logger LOGGER = Logger.getLogger(OrderService.class.getName());

    // trxId mirrors request_id under the CloudWatch source's field naming, so
    // the same identifier is findable under either source's vocabulary.
    static final String COMPONENT_ID = "orders-service";

    String retrieveOrder(String requestId, String username, String orderId) {
        LOGGER.info("request_id=" + requestId + " order retrieved order_id=" + orderId
                + tail(requestId, username));
        return orderId;
    }

    String createOrder(String requestId, String username, String sku) {
        String orderId = "ord-" + Integer.toHexString(sku.hashCode() & 0xffffff);
        LOGGER.info("request_id=" + requestId + " order created order_id=" + orderId + " sku=" + sku
                + tail(requestId, username));
        return orderId;
    }

    // Deliberately undguarded: the null catalog entry surfaces as a real NPE
    // with a genuine multi-frame stack trace, not a manually thrown one.
    void lookupWithBrokenCatalog(String requestId) {
        OrderCatalogEntry entry = fetchCatalogEntry(requestId);
        entry.describe();
    }

    private OrderCatalogEntry fetchCatalogEntry(String requestId) {
        return null;
    }

    void reportDbFailure(String requestId, String username, String orderId) {
        LOGGER.log(Level.SEVERE, "request_id=" + requestId
                + " DB connection failed for order lookup order_id=" + orderId
                + " error_code=DB_TIMEOUT"
                + tail(requestId, username));
    }

    private static String tail(String requestId, String username) {
        return " trxId=" + requestId + " username=" + username + " componentId=" + COMPONENT_ID;
    }

    private static final class OrderCatalogEntry {
        void describe() {
            // never reached; lookupWithBrokenCatalog() NPEs before this point
        }
    }
}
