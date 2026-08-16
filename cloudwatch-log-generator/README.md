# cloudwatch-log-generator

A Java 21 / Quarkus service that continuously generates synthetic application
logs and ships them to Amazon CloudWatch Logs when run on AWS ECS. It's a
small, self-contained load/test-data generator: point it at a log group and
it produces a realistic-looking stream of INFO/WARN/ERROR/DEBUG events,
either fully random or "correlated" around a fixed transaction.

## How it decides what to log

Every generated event carries three identifiers - `trxId`, `username`,
`componentId` - controlled by one boolean environment variable:

| `generateCorrelatedLogs` | Behavior |
|---|---|
| `true` | Every event reuses the `trxId`, `username`, `componentId` values from their matching environment variables, so the whole stream of logs looks like it belongs to one ongoing transaction/session. If one of those three is left unset, the app generates a single random value for it at startup and reuses that same value for the life of the task (it doesn't fail, and it doesn't drift to a new value every line). |
| `false` (default) | A brand-new random `trxId`/`username`/`componentId` is generated for every single log line, independent of anything configured. |

## How logs reach CloudWatch

The app never calls the CloudWatch API. It logs structured JSON to stdout
(via `quarkus-logging-json`); in ECS, the container's `awslogs` log driver
(configured in the task definition, see `ecs/task-definition.json`) is what
ships each stdout line to the CloudWatch Logs group. This is the standard,
credential-free way to get container logs into CloudWatch and is why the
task role doesn't need `logs:PutLogEvents` - only the ECS agent/execution
role does (via `ecsTaskExecutionRole`, already handled by AWS).

Each JSON log line looks like:

```json
{
  "timestamp": "2026-08-15T14:32:01.512Z",
  "sequence": 8821,
  "loggerClassName": "org.jboss.logging.Logger",
  "loggerName": "cloudwatch-log-generator",
  "level": "INFO",
  "message": "Payment authorized | trxId=a1b2c3d4-e5f6-4711-9abc-1234567890ab username=svc-account-001 componentId=order-service trace_id=a1b2c3d4-e5f6-4711-9abc-1234567890ab request_id=a1b2c3d4-e5f6-4711-9abc-1234567890ab user_id=svc-account-001 service_name=order-service",
  "threadName": "executor-thread-1",
  "mdc": {
    "trxId": "a1b2c3d4-e5f6-4711-9abc-1234567890ab",
    "username": "svc-account-001",
    "componentId": "order-service",
    "correlated": "true",
    "applicationName": "order-service-log-generator"
  },
  "hostName": "ip-10-0-1-42.ec2.internal"
}
```

`trxId`/`username`/`componentId` appear twice by design: as first-class,
queryable fields under `mdc` (good for CloudWatch Logs Insights queries
like `fields mdc.trxId | filter mdc.correlated = "true"`), and as
`key=value` tokens inside the free-text `message` (good for `filter
@message like /trxId=.../`, and for regex-based extraction - see below).

### Compatibility with `log_correlation_poc`

This folder also contains `log_correlation_poc`, whose CloudWatch extractor
pulls raw log text and runs it through regexes looking for
`trace_id`/`request_id`/`user_id`/`service_name`/`error_code` tokens
(`normalization/normalizer.py`). By default
(`log.generator.emit-correlation-aliases=true`), every generated message
also includes those exact tokens (`trace_id=...`, `request_id=...`,
`user_id=...`, `service_name=...`, and `error_code=...` on WARN/ERROR
events), aliased from the same trxId/username/componentId values. That means
you can point `log_correlation_poc` at this generator's CloudWatch log group
and get a working, correlate-able dataset for free - run it in correlated
mode and every event from that task links into a single incident; run it in
random mode to generate background noise. Set
`LOG_GENERATOR_EMIT_CORRELATION_ALIASES=false` if you don't want those extra
tokens.

## Configuration reference

All values are environment variables in the ECS task definition; the ones
in the first table are exact-name matches (no case conversion, no prefix),
the rest use the standard Quarkus `SCREAMING_SNAKE_CASE` convention.

| Environment variable | Type | Default | Meaning |
|---|---|---|---|
| `generateCorrelatedLogs` | boolean | `false` | Correlated vs. fully random mode (see above). |
| `trxId` | string | *(random if unset)* | Transaction id reused for every event when correlated. |
| `username` | string | *(random if unset)* | Username reused for every event when correlated. |
| `componentId` | string | *(random if unset)* | Component/service name reused for every event when correlated. |

| Environment variable | Type | Default | Meaning |
|---|---|---|---|
| `LOG_GENERATOR_INTERVAL` | duration | `5s` | How often a batch of log lines is generated (`500ms`, `5s`, `1m`, ...). |
| `LOG_GENERATOR_BATCH_SIZE` | int | `1` | How many log lines are emitted per interval tick. |
| `LOG_GENERATOR_APPLICATION_NAME` | string | `cloudwatch-log-generator` | Stamped into the `applicationName` MDC field; use this to tell apart several instances of this image running with different roles/log groups. |
| `LOG_GENERATOR_EMIT_CORRELATION_ALIASES` | boolean | `true` | Whether to append the `log_correlation_poc`-compatible alias tokens described above. |

Two example task definitions are provided in `ecs/`:
`task-definition.json` (correlated mode) and
`task-definition.random-mode.json` (random mode, higher throughput).
Replace `<ACCOUNT_ID>` and `<REGION>` before registering either one.

## Project layout

```
src/main/java/com/coderoad/logs/
  config/CorrelationConfig.java      resolves trxId/username/componentId per the boolean flag
  generator/RandomLogValues.java     pure random value generators (usernames, components, messages, ...)
  generator/LogEventComposer.java    pure function: builds the final message text
  generator/LogGeneratorScheduler.java  @Scheduled bean that ties it together and logs
  health/LogGeneratorHealthCheck.java   /q/health for the ECS container health check
src/main/resources/application.properties
src/main/docker/Dockerfile.jvm
ecs/task-definition.json, ecs/task-definition.random-mode.json
```

## Build and run locally

Requires Java 21 and Maven (or use the `./mvnw` wrapper once you've run
`mvn -N io.takari:maven:wrapper` if you want one).

```bash
# Dev mode (live reload), random mode:
mvn quarkus:dev

# Dev mode, correlated mode:
generateCorrelatedLogs=true trxId=demo-trx-00000001 username=demo-user componentId=demo-service \
  mvn quarkus:dev

# Run the tests
mvn test

# Build a runnable jar (fast-jar layout under target/quarkus-app/)
mvn package
java -jar target/quarkus-app/quarkus-run.jar
```

Once running, check `http://localhost:8080/q/health` and watch stdout for
one JSON log line every `LOG_GENERATOR_INTERVAL` (5s by default).

## Build and push the container image

The task definitions in `ecs/` target `runtimePlatform.cpuArchitecture:
X86_64` (the Fargate default). If you build on an Apple Silicon Mac, or any
other arm64 machine, without pinning the platform, Docker produces an arm64
image; running that under an x86_64 Fargate task fails immediately with
`exec format error` / "essential container exited", which then trips the
deployment circuit breaker. Always build with `buildx` and an explicit
`--platform`.

Tag images with something immutable (here, the current git commit SHA)
rather than `:latest`. With a floating `:latest` tag, every task definition
revision resolves to whatever was pushed most recently, so an ECS rollback
to an older revision still pulls the same (possibly broken) image instead of
reverting to a known-good one.

```bash
mvn package

IMAGE_TAG=$(git rev-parse --short HEAD)
docker buildx build --platform linux/amd64 \
  -f src/main/docker/Dockerfile.jvm \
  -t cloudwatch-log-generator:$IMAGE_TAG .

# Push to ECR
cd /Users/coderoad/Projects/smartlog/cloudwatch-log-generator
mvn package
docker buildx build --platform linux/amd64 -f src/main/docker/Dockerfile.jvm -t cloudwatch-log-generator:latest .
aws ecr get-login-password --region us-east-2 --profile smartlog | docker login --username AWS --password-stdin 105430337985.dkr.ecr.us-east-2.amazonaws.com
docker tag cloudwatch-log-generator:latest 105430337985.dkr.ecr.us-east-2.amazonaws.com/cloudwatch-log-generator:latest
docker push 105430337985.dkr.ecr.us-east-2.amazonaws.com/cloudwatch-log-generator:latest
```

## Deploy to ECS

1. Create (or confirm) the CloudWatch Logs group, e.g. `/ecs/cloudwatch-log-generator` - the task definitions here set `awslogs-create-group: true` so ECS will create it on first run if it doesn't exist, as long as the execution role has `logs:CreateLogGroup`.
2. Fill in `<ACCOUNT_ID>` / `<REGION>` / `<IMAGE_TAG>` in `ecs/task-definition.json` (or the random-mode variant) - use the same tag you just pushed - and register it:
   ```bash
   aws ecs register-task-definition --cli-input-json file://ecs/task-definition.json
   ```
3. Run it as an ECS service (or a one-off `run-task`) on a Fargate cluster, in a subnet with a route to ECR and CloudWatch Logs (a NAT gateway, or VPC endpoints for `ecr.api`/`ecr.dkr`/`logs`/`s3`).
4. To change behavior later - flip correlated/random mode, change the interval, rotate `trxId` for a new test transaction - just edit the task definition's `environment` block and redeploy; no code or image change needed. To roll out a new image, register a new task definition revision with the new `<IMAGE_TAG>` and update the service:
   ```bash
   aws ecs update-service --cluster <CLUSTER> --service <SERVICE> \
     --task-definition cloudwatch-log-generator --force-new-deployment
   ```

## Tests

`mvn test` runs:
- Plain JUnit 5 tests for `RandomLogValues` and `LogEventComposer` (value shapes, alias-token regex compatibility).
- `@QuarkusTest` tests for `CorrelationConfig` under three `@TestProfile`s: correlated-with-values-set, correlated-with-values-unset (fallback caching), and random mode.
- `@QuarkusTest` + REST Assured tests for the `/q/health` endpoints.

> **Note on this repository as delivered:** it was generated in a sandboxed
> environment without access to Maven Central, so `mvn package`/`mvn test`
> could not be executed here to confirm a clean build. The code was written
> and reviewed carefully against current Quarkus 3.33 LTS APIs, but please
> run `mvn test` yourself as the first step after unpacking it.


---
cd /Users/coderoad/Projects/smartlog/cloudwatch-log-generator
mvn package
IMAGE_TAG=$(git rev-parse --short HEAD)
docker buildx build --platform linux/X86_64 -f src/main/docker/Dockerfile.jvm -t cloudwatch-log-generator:latest .
aws ecr get-login-password --region us-east-2 --profile smartlog | docker login --username AWS --password-stdin 105430337985.dkr.ecr.us-east-2.amazonaws.com
docker tag cloudwatch-log-generator:$IMAGE_TAG 105430337985.dkr.ecr.us-east-2.amazonaws.com/cloudwatch-log-generator:$IMAGE_TAG
docker push 105430337985.dkr.ecr.us-east-2.amazonaws.com/cloudwatch-log-generator:$IMAGE_TAG