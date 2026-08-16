package com.coderoad.logs.health;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.is;

import org.junit.jupiter.api.Test;

import io.quarkus.test.junit.QuarkusTest;

@QuarkusTest
class LogGeneratorHealthCheckTest {

    @Test
    void healthEndpointReportsUp() {
        given().when().get("/q/health").then().statusCode(200).body("status", is("UP"));
    }

    @Test
    void livenessEndpointReportsUp() {
        given().when().get("/q/health/live").then().statusCode(200).body("status", is("UP"));
    }

    @Test
    void readinessEndpointReportsUp() {
        given().when().get("/q/health/ready").then().statusCode(200).body("status", is("UP"));
    }
}
