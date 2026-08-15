# syntax=docker/dockerfile:1

FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build
COPY pom.xml .
COPY src ./src
RUN mvn -q -B package

FROM tomcat:10.1-jdk17-temurin

# Deployed as ROOT.war so endpoints are served with no context path
# (/api/orders, /health) instead of /order-log-source/api/orders.
RUN rm -rf "$CATALINA_HOME/webapps/ROOT"
COPY --from=build /build/target/ROOT.war "$CATALINA_HOME/webapps/ROOT.war"

EXPOSE 8080

# $CATALINA_HOME/logs is left unrelocated on purpose. On EC2, bind-mount
# this directory to a host path (e.g. /var/log/tomcat/) so it lines up with
# this repo's TOMCAT_LOG_PATHS=/var/log/tomcat/catalina.out. No VOLUME
# instruction here to avoid an anonymous volume shadowing that bind mount —
# see docker-compose.yml / README.md for the actual mount.

# The base image's default CMD runs "catalina.sh run" in the foreground and
# relies on the container runtime to capture stdout/stderr — it does NOT
# produce a catalina.out file (that file is only written when Tomcat is
# started in the background via "catalina.sh start"). Redirect explicitly so
# a real catalina.out exists to bind-mount; "exec" keeps the Java process as
# PID 1 so it still receives SIGTERM correctly. This means `docker logs`
# will be empty — check the bind-mounted catalina.out instead.
CMD ["/bin/sh", "-c", "exec catalina.sh run >> \"$CATALINA_HOME/logs/catalina.out\" 2>&1"]
