-- Test-only role bootstrap. Real environments create these via infra (IaC), with LOGIN users granted membership.
CREATE ROLE ctx_owner NOLOGIN;
CREATE ROLE ctx_gateway NOLOGIN NOBYPASSRLS;
CREATE ROLE ctx_security NOLOGIN NOBYPASSRLS;
CREATE ROLE core_owner NOLOGIN;
CREATE ROLE core_app NOLOGIN NOBYPASSRLS;
