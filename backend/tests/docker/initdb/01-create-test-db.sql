-- Runs once on first container start (empty data directory) to create the
-- database the test suite uses. The suite connects to this instead of the
-- application database, so test data can never leak into what the app serves.
--
-- The postgres entrypoint runs every *.sql in this directory, as POSTGRES_USER,
-- connected to POSTGRES_DB. CREATE DATABASE is the only statement needed here;
-- the PostGIS extension itself is created by app.main._ensure_schema().
CREATE DATABASE aegisai_test;
