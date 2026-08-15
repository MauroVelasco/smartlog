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
        RequestContext ctx = RequestContext.fromRequest(req);
        String pathInfo = req.getPathInfo() == null ? "" : req.getPathInfo();

        resp.setContentType("application/json");

        switch (pathInfo) {
            case "/error":
                handleError(ctx, resp);
                break;
            case "/db-error":
                handleDbError(ctx, resp);
                break;
            case "":
            case "/":
                handleList(ctx, req, resp);
                break;
            default:
                resp.setStatus(HttpServletResponse.SC_NOT_FOUND);
                resp.getWriter().write("{\"request_id\":\"" + ctx.trxId() + "\",\"error\":\"not found\"}");
        }
    }

    private void handleList(RequestContext ctx, HttpServletRequest req, HttpServletResponse resp) throws IOException {
        String sku = req.getParameter("sku");
        String orderId = sku != null
                ? orderService.createOrder(ctx, sku)
                : orderService.retrieveOrder(ctx, "ord-" + Integer.toHexString(ctx.trxId().hashCode() & 0xfff));

        resp.setStatus(HttpServletResponse.SC_OK);
        resp.getWriter().write("{\"request_id\":\"" + ctx.trxId() + "\",\"order_id\":\"" + orderId + "\"}");
    }

    private void handleError(RequestContext ctx, HttpServletResponse resp) throws IOException {
        try {
            orderService.lookupWithBrokenCatalog(ctx.trxId());
        } catch (NullPointerException e) {
            LOGGER.log(Level.SEVERE, "request_id=" + ctx.trxId() + " " + e.getClass().getSimpleName()
                    + OrderService.tail(ctx), e);
            resp.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            resp.getWriter().write("{\"request_id\":\"" + ctx.trxId() + "\",\"error\":\"internal error\"}");
        }
    }

    private void handleDbError(RequestContext ctx, HttpServletResponse resp) throws IOException {
        String orderId = "ord-" + Integer.toHexString(ctx.trxId().hashCode() & 0xfff);
        orderService.reportDbFailure(ctx, orderId);
        resp.setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
        resp.getWriter().write("{\"request_id\":\"" + ctx.trxId() + "\",\"error\":\"db unavailable\"}");
    }
}
