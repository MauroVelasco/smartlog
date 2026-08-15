package com.example;

import java.util.logging.Level;
import java.util.logging.Logger;

class OrderService {

    private static final Logger LOGGER = Logger.getLogger(OrderService.class.getName());

    String retrieveOrder(String requestId, String orderId) {
        LOGGER.info("request_id=" + requestId + " order retrieved order_id=" + orderId);
        return orderId;
    }

    String createOrder(String requestId, String sku) {
        String orderId = "ord-" + Integer.toHexString(sku.hashCode() & 0xffffff);
        LOGGER.info("request_id=" + requestId + " order created order_id=" + orderId + " sku=" + sku);
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

    void reportDbFailure(String requestId, String orderId) {
        LOGGER.log(Level.SEVERE, "request_id=" + requestId
                + " DB connection failed for order lookup order_id=" + orderId
                + " error_code=DB_TIMEOUT");
    }

    private static final class OrderCatalogEntry {
        void describe() {
            // never reached; lookupWithBrokenCatalog() NPEs before this point
        }
    }
}
