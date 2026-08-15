package com.example;

import jakarta.servlet.ServletException;
import jakarta.servlet.annotation.WebServlet;
import jakarta.servlet.http.HttpServlet;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import java.io.IOException;
import java.util.logging.Level;
import java.util.logging.Logger;

@WebServlet(urlPatterns = "/api/orders/*")
public class OrderServlet extends HttpServlet {

    private static final Logger LOGGER = Logger.getLogger(OrderServlet.class.getName());

    private final OrderService orderService = new OrderService();

    @Override
    protected void doGet(HttpServletRequest req, HttpServletResponse resp) throws ServletException, IOException {
        String requestId = RequestIds.next();
        String username = Users.next();
        String pathInfo = req.getPathInfo() == null ? "" : req.getPathInfo();

        resp.setContentType("application/json");

        switch (pathInfo) {
            case "/error":
                handleError(requestId, username, resp);
                break;
            case "/db-error":
                handleDbError(requestId, username, resp);
                break;
            case "":
            case "/":
                handleList(requestId, username, req, resp);
                break;
            default:
                resp.setStatus(HttpServletResponse.SC_NOT_FOUND);
                resp.getWriter().write("{\"request_id\":\"" + requestId + "\",\"error\":\"not found\"}");
        }
    }

    private void handleList(String requestId, String username, HttpServletRequest req, HttpServletResponse resp) throws IOException {
        String sku = req.getParameter("sku");
        String orderId = sku != null
                ? orderService.createOrder(requestId, username, sku)
                : orderService.retrieveOrder(requestId, username, "ord-" + Integer.toHexString(requestId.hashCode() & 0xfff));

        resp.setStatus(HttpServletResponse.SC_OK);
        resp.getWriter().write("{\"request_id\":\"" + requestId + "\",\"order_id\":\"" + orderId + "\"}");
    }

    private void handleError(String requestId, String username, HttpServletResponse resp) throws IOException {
        try {
            orderService.lookupWithBrokenCatalog(requestId);
        } catch (NullPointerException e) {
            LOGGER.log(Level.SEVERE, "request_id=" + requestId + " " + e.getClass().getSimpleName()
                    + " trxId=" + requestId + " username=" + username + " componentId=" + OrderService.COMPONENT_ID, e);
            resp.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            resp.getWriter().write("{\"request_id\":\"" + requestId + "\",\"error\":\"internal error\"}");
        }
    }

    private void handleDbError(String requestId, String username, HttpServletResponse resp) throws IOException {
        String orderId = "ord-" + Integer.toHexString(requestId.hashCode() & 0xfff);
        orderService.reportDbFailure(requestId, username, orderId);
        resp.setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
        resp.getWriter().write("{\"request_id\":\"" + requestId + "\",\"error\":\"db unavailable\"}");
    }
}
