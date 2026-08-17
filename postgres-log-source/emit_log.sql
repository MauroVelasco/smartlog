-- harness.emit_log(): lets a caller (trigger.py / the scenario harness) make
-- the live Postgres server emit a real server-log line at INFO/WARNING/ERROR
-- with caller-specified identifier fields, WITHOUT breaking the caller's
-- CONNECTION (session) on the ERROR path.
--
-- DEVIATION FROM DESIGN (validated empirically against a live Postgres
-- 16.14 container, see postgres-scenario-harness apply-progress): the
-- design proposed catching RAISE EXCEPTION server-side in a nested
-- BEGIN ... EXCEPTION WHEN OTHERS THEN NULL END block, on the theory that
-- errfinish() writes the log line before the stack unwinds to any handler,
-- so catching it afterwards would not suppress the log line. Empirically,
-- on Postgres 16.14, a RAISE EXCEPTION caught by a PL/pgSQL exception
-- handler writes NOTHING to the server log — confirmed both via
-- harness.emit_log() and a minimal DO $$ BEGIN BEGIN RAISE EXCEPTION ...
-- EXCEPTION WHEN OTHERS THEN NULL; END; END; $$ repro. Only an UNCAUGHT
-- RAISE EXCEPTION produces an ERROR:-severity log line.
--
-- The fix is simpler than the design's approach: let RAISE EXCEPTION
-- propagate uncaught. The "caller's connection must survive" requirement
-- is satisfied a different way — not by catching the error server-side,
-- but by the caller using a psycopg2 connection with autocommit=True.
-- Under autocommit, each statement is its own implicit transaction; an
-- uncaught error aborts only THAT statement's transaction, not the
-- connection/session, so the very next statement on the same connection
-- succeeds normally (verified: cur.execute() raises a Python exception,
-- then a follow-up cur.execute("SELECT 1") on the same connection/cursor
-- returns fine, no ROLLBACK needed). See trigger.py's emit_log(), which
-- catches the expected exception on the ERROR path.
--
-- log_error_verbosity=terse + log_min_error_statement=panic (set in
-- docker-compose.yml) keep the resulting ERROR line to a single line
-- (no CONTEXT:/STATEMENT: continuation lines that would otherwise parse
-- as separate RawLogRecords and leak the full argument list back into
-- the log).

CREATE SCHEMA IF NOT EXISTS harness;

CREATE OR REPLACE FUNCTION harness.emit_log(
    p_level           text,                       -- 'INFO' | 'WARNING' | 'ERROR'
    p_message         text,
    p_trx_id          text    DEFAULT NULL,
    p_username        text    DEFAULT NULL,
    p_component_id    text    DEFAULT NULL,
    p_error_code      text    DEFAULT NULL,
    p_identifier_free boolean DEFAULT false
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_line text := p_message;
BEGIN
    -- identifier-free mode: append nothing. Suppressing the regex-matchable
    -- names (request_id/trace_id/user_id/service_name/error_code) AND the
    -- friendly ones is deliberate — an identical trxId on two lines is a
    -- free giveaway to the semantic LLM stage even though it matches no
    -- CORRELATION_KEY_PATTERNS regex.
    IF NOT p_identifier_free THEN
        IF p_trx_id       IS NOT NULL THEN v_line := v_line || ' request_id=' || p_trx_id || ' trace_id=' || p_trx_id; END IF;
        IF p_username     IS NOT NULL THEN v_line := v_line || ' user_id='      || p_username;     END IF;
        IF p_component_id IS NOT NULL THEN v_line := v_line || ' service_name=' || p_component_id; END IF;
        IF p_error_code   IS NOT NULL THEN v_line := v_line || ' error_code='   || p_error_code;   END IF;
    END IF;

    IF    p_level = 'INFO'    THEN RAISE INFO    '%', v_line;
    ELSIF p_level = 'WARNING' THEN RAISE WARNING '%', v_line;
    ELSIF p_level = 'ERROR'   THEN
        -- Deliberately UNCAUGHT — see header comment. Only an uncaught
        -- RAISE EXCEPTION writes an ERROR:-severity server log line; the
        -- caller (trigger.py, autocommit=True) catches this and keeps
        -- using the same connection for its next statement. Tagged with a
        -- distinct custom SQLSTATE (ZZ001, outside Postgres's own
        -- allocated ranges) so the caller can distinguish "expected
        -- harness ERROR emission" from a genuine bug (e.g. the unsupported
        -- -level branch below, which keeps the default P0001 code).
        RAISE EXCEPTION '%', v_line USING ERRCODE = 'ZZ001';
    ELSE
        -- Also deliberately NOT caught: the case set only reasons about
        -- INFO/WARNING/ERROR, so an unsupported level is a caller bug,
        -- not a scenario to silently degrade.
        RAISE EXCEPTION 'harness.emit_log: unsupported level %', p_level;
    END IF;
END;
$$;
