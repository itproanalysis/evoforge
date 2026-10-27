"""API-side client for the isolated Runner service (T16).

When EVO_RUNNER_URL is set, /v1/runs bundles the T15-resolved repo dir
(history up to base only) and POSTs bundle + diff + suites to the Runner.
When unset, callers fall back to the in-process runner (dev).
"""
from __future__ import annotations

import base64
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request


class RunnerClientError(ValueError):
    """Runner unreachable or malformed reply -> API 502."""


class RunnerBadRequest(RunnerClientError):
    """Runner answered 400 -> API 400."""


class RunnerConflict(RunnerClientError):
    """Runner answered 409 -> API 409."""


class RunnerTooLarge(RunnerClientError):
    """Runner answered 413 -> API 413."""


def runner_url() -> str:
    return (os.getenv("EVO_RUNNER_URL", "") or "").strip().rstrip("/")


def _audience() -> str:
    return (os.getenv("EVO_RUNNER_AUDIENCE", "") or "").strip()


def _id_token(audience: str) -> str:
    url = ("http://metadata.google.internal/computeMetadata/v1/instance/"
           "service-accounts/default/identity?audience="
           + urllib.parse.quote(audience, safe="") + "&format=full")
    req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace").strip()
    except Exception as e:
        raise RunnerClientError(f"runner identity token fetch failed: {e}")


def _auth_headers() -> dict:
    audience = _audience()
    if not audience:
        return {}
    token = _id_token(audience)
    if not token:
        raise RunnerClientError("runner identity token fetch failed")
    return {"Authorization": f"Bearer {token}"}


def _remove_tree(path: str) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def _head_sha(repo_dir: str) -> str:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir,
                              capture_output=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", errors="replace").strip()


def _resolve_commit(repo_dir: str, ref: str) -> str:
    """Resolve a ref exactly once before creating a bundle or calling the Runner."""
    if not isinstance(ref, str) or not ref.strip():
        raise RunnerBadRequest("base checkout failed")
    try:
        proc = subprocess.run(["git", "rev-parse", "--verify", "--end-of-options", f"{ref.strip()}^{{commit}}"],
                              cwd=repo_dir, capture_output=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RunnerClientError(f"base resolution failed: {type(exc).__name__}") from None
    sha = proc.stdout.decode("ascii", errors="replace").strip()
    # The Runner bundle protocol currently accepts Git SHA-1 object IDs.
    if proc.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RunnerBadRequest("base checkout failed")
    return sha


def _create_bundle(repo_dir: str, base_sha: str) -> str:
    """Bundle history up to base_sha into a temp file; returns its path."""
    if not isinstance(base_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", base_sha):
        raise RunnerBadRequest("bundle base must be an immutable SHA-1 commit")
    try:
        fd, bundle_path = tempfile.mkstemp(prefix="evoforge-bundle-", suffix=".bundle")
    except OSError as e:
        raise RunnerClientError(f"bundle create failed: {e}")
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        # Start from a clean path: some git builds refuse to write a bundle
        # over a pre-existing file.
        os.remove(bundle_path)
    except OSError:
        pass
    branch = f"__evo_bundle_{os.getpid()}_{secrets.token_hex(4)}"
    created = False
    complete = False
    try:
        try:
            proc = subprocess.run(["git", "branch", branch, base_sha], cwd=repo_dir,
                                  capture_output=True, timeout=60)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise RunnerClientError(f"bundle create failed: {type(e).__name__}")
        if proc.returncode != 0:
            raise RunnerBadRequest("base checkout failed")
        created = True
        try:
            proc = subprocess.run(["git", "bundle", "create", bundle_path, branch], cwd=repo_dir,
                                  capture_output=True, timeout=120)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise RunnerClientError(f"bundle create failed: {type(e).__name__}")
        if proc.returncode != 0 or not os.path.exists(bundle_path):
            raise RunnerBadRequest("bundle create failed")
        try:
            proc = subprocess.run(["git", "bundle", "list-heads", bundle_path], cwd=repo_dir,
                                  capture_output=True, timeout=60)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise RunnerClientError(f"bundle verification failed: {type(e).__name__}") from None
        expected = f"{base_sha} refs/heads/{branch}"
        if proc.returncode != 0 or proc.stdout.decode("ascii", errors="replace").strip() != expected:
            raise RunnerClientError("bundle base changed before verification")
        complete = True
        return bundle_path
    finally:
        if created:
            try:
                subprocess.run(["git", "update-ref", "--no-deref", "-d", f"refs/heads/{branch}", base_sha],
                               cwd=repo_dir, capture_output=True, timeout=60)
            except (subprocess.TimeoutExpired, OSError):
                pass
        if not complete:
            try:
                os.remove(bundle_path)
            except OSError:
                pass


def _validate_counts(section: object, name: str) -> dict:
    if not isinstance(section, dict):
        raise RunnerClientError(f"malformed runner reply ({name})")
    for key in ("pass", "n"):
        val = section.get(key)
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            raise RunnerClientError(f"malformed runner reply ({name}.{key})")
    if section['pass'] > section['n']:
        raise RunnerClientError(f"malformed runner reply ({name}: pass exceeds n)")
    if not isinstance(section.get("timed_out"), bool):
        raise RunnerClientError(f"malformed runner reply ({name}.timed_out)")
    exit_code = section.get("exit_code")
    if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
        raise RunnerClientError(f"malformed runner reply ({name}.exit_code)")
    return {"pass": section["pass"], "n": section["n"],
            "timed_out": section["timed_out"], "exit_code": exit_code}


def _validate_collection(section: dict, supplied_count: int, name: str) -> None:
    """Reject a claimed success that cannot cover the suite sent to the Runner."""
    if supplied_count == 0 and section["n"] != 0:
        raise RunnerClientError(f"malformed runner reply ({name}: tests were not supplied)")
    claimed_success = section["n"] > 0 and section["pass"] == section["n"] and not section["timed_out"]
    if claimed_success and (section["exit_code"] != 0 or section["n"] < supplied_count):
        raise RunnerClientError(f"malformed runner reply ({name}: incomplete or unsuccessful collection)")


def run_via_runner(source_repo, base_sha, diff, visible_tests, sealed_tests,
                   timeout_s: int = 120) -> dict:
    """Execute via the remote Runner; returns the run dict for gate evaluation."""
    from evoforge import repo_source

    url = runner_url()
    if not url:
        raise RunnerClientError("runner URL not configured")
    try:
        source = repo_source.resolve_repo_dir(source_repo, base_sha)
    except Exception as e:
        raise RunnerBadRequest(repo_source.redact(str(e)))

    is_temp = isinstance(source_repo, str) and source_repo in ("", "github")
    bundle_path = None
    try:
        requested_base = base_sha.strip() if isinstance(base_sha, str) else ""
        if is_temp:
            if re.fullmatch(r"[0-9a-fA-F]{64}", requested_base):
                raise RunnerBadRequest("base checkout requires a SHA-1 commit")
            head = _head_sha(source)
            if not re.fullmatch(r"[0-9a-f]{40}", head):
                raise RunnerBadRequest("base checkout failed")
            if re.fullmatch(r"[0-9a-fA-F]{40}", requested_base) and head != requested_base.lower():
                raise RunnerBadRequest("base checkout does not match requested commit")
            effective_base = _resolve_commit(source, head)
        else:
            effective_base = _resolve_commit(source, requested_base)
        try:
            bundle_path = _create_bundle(source, effective_base)
        except RunnerBadRequest:
            raise
        except RunnerClientError:
            raise
        except Exception as e:
            raise RunnerClientError(f"bundle create failed: {e}")
        try:
            with open(bundle_path, "rb") as fh:
                bundle_bytes = fh.read()
        except OSError as e:
            raise RunnerClientError(f"bundle read failed: {e}")
        payload = {
            "bundle_b64": base64.b64encode(bundle_bytes).decode("ascii"),
            "base_sha": effective_base,
            "diff": diff if isinstance(diff, str) else "",
            "visible": [{"code": t.get("code")} if isinstance(t, dict) else {"code": t}
                        for t in (visible_tests or [])],
            "sealed": [{"code": t.get("code"), "kind": t.get("kind", "")} if isinstance(t, dict)
                       else {"code": t, "kind": ""}
                       for t in (sealed_tests or [])],
            "timeout_s": timeout_s,
        }
        headers = _auth_headers()
        try:
            import httpx
        except ImportError as e:
            raise RunnerClientError(f"runner http client unavailable: {e}")
        try:
            resp = httpx.post(f"{url}/run", json=payload, headers=headers,
                              timeout=timeout_s + 30)
        except Exception as e:
            raise RunnerClientError(f"runner unreachable: {type(e).__name__}")
        if resp.status_code == 400:
            raise RunnerBadRequest(resp.text[:500])
        if resp.status_code == 409:
            raise RunnerConflict(resp.text[:500])
        if resp.status_code == 413:
            raise RunnerTooLarge(resp.text[:500])
        if resp.status_code != 200:
            raise RunnerClientError(f"runner error {resp.status_code}")
        try:
            data = resp.json()
        except Exception:
            raise RunnerClientError("malformed runner reply (not JSON)")
        if not isinstance(data, dict):
            raise RunnerClientError("malformed runner reply")
        base = data.get("base")
        if not isinstance(base, str) or base != effective_base:
            raise RunnerClientError("malformed runner reply (base mismatch)")
        visible = _validate_counts(data.get("visible"), "visible")
        heldout = _validate_counts(data.get("heldout"), "heldout")
        _validate_collection(visible, len(payload["visible"]), "visible")
        _validate_collection(heldout, len(payload["sealed"]), "heldout")
        kinds = data.get("heldout_kinds")
        if not isinstance(kinds, list) or any(not isinstance(k, str) for k in kinds):
            raise RunnerClientError("malformed runner reply (heldout_kinds)")
        if kinds != [test.get("kind", "") for test in payload["sealed"]]:
            raise RunnerClientError("malformed runner reply (heldout_kinds mismatch)")
        if data.get('hygiene', []) != []:
            raise RunnerClientError('runner sandbox hygiene failed')
        result = {"base": base, "hygiene": [], "visible": visible,
                  "heldout": heldout, "heldout_kinds": list(kinds)}
        from evoforge import runner_attestation
        try:
            expected_image = runner_attestation.configured_image()
            if expected_image or 'attestation' in data:
                result['attestation'] = data.get('attestation')
                runner_attestation.verify(result,effective_base,diff or '',visible_tests,sealed_tests,expected_image)
        except (ValueError,TypeError,KeyError,UnicodeError):
            raise RunnerClientError('Runner provenance validation failed') from None
        return result
    finally:
        if bundle_path:
            try:
                os.remove(bundle_path)
            except OSError:
                pass
        if is_temp:
            _remove_tree(source)
