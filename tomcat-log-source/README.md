# tomcat-log-source

A minimal, synthetic Java + Tomcat web app that exists solely to produce
realistic `catalina.out` output for the `smartlog` demo. It simulates an
"orders" service; the actual business logic is fake, the log lines are the
point. It runs on stock Tomcat 10.1 juli logging with no custom formatter,
so the timestamp format (`dd-MMM-yyyy HH:mm:ss.SSS`) matches what
`extraction/tomcat_extractor.py` expects out of the box.

## Stack

- Java 17
- Jakarta Servlet API 6.0 (annotation-mapped servlets, no `web.xml`)
- Tomcat 10.1 (Jakarta EE 10 baseline)
- Maven, packaged as a `war`

## Running locally

```bash
cd tomcat-log-source
docker compose up --build
```

The app is served at `http://localhost:8080/` (deployed as `ROOT.war`, no
context path prefix). Logs land in `./logs/catalina.out` on the host via a
bind mount. `docker compose logs` will be empty — the container's CMD
redirects stdout/stderr straight into `catalina.out` so a real file exists
to bind-mount (the base Tomcat image's default foreground CMD does not
produce one on its own; tail the file instead: `tail -f logs/catalina.out`).

## Endpoints

- `GET /api/orders` — normal path. Logs an INFO line with a fresh
  `request_id=req-xxxxxx` and a message like "order retrieved" or "order
  created" (pass `?sku=...` to hit the create path). Returns 200 JSON.
- `GET /api/orders/error` — triggers a real `NullPointerException` two
  method calls deep, caught and logged as SEVERE with `request_id=` in the
  header line and a genuine multi-frame stack trace underneath. Returns
  500.
- `GET /api/orders/db-error` — logs a SEVERE line simulating a downstream
  DB failure (`request_id=`, `error_code=DB_TIMEOUT`), for correlating
  against DB-source logs in the demo. Returns 503.
- `GET /health` — plain 200 OK for container health checks, minimal
  logging.

Every request generates and logs its own `request_id`, so each one is
independently traceable through the pipeline.

## Deploying to EC2

1. Get this app onto the instance — clone the full repo, or just copy the
   `tomcat-log-source/` subdirectory.
2. `cd tomcat-log-source && docker compose up -d --build`
3. Logs accumulate at `tomcat-log-source/logs/catalina.out` on the EC2
   host.
4. Point `TOMCAT_LOG_PATHS` in the main project's `.env` at that path,
   e.g. `TOMCAT_LOG_PATHS=/home/ec2-user/smartlog/tomcat-log-source/logs/catalina.out`.

**Constraint:** `TOMCAT_LOG_PATHS` is read from local disk by the Python
extractor. If the extractor runs on a different machine than this EC2
instance, the log file has to be shipped or synced over first — e.g. via
S3, rsync, or the CloudWatch agent. There's nothing automatic about that
transfer; this app only guarantees the log file exists locally on the
instance it runs on.
