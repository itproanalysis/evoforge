"""Runner-owned input/result hashes and a deployment-configured image identity.

These are provenance metadata, not a signature or independent image measurement.
Only a trusted Runner transport and append-only server evidence may supply them.
"""
import hashlib
import json
import os
import re


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def configured_image():
    image = os.getenv('EVO_RUNNER_IMAGE_DIGEST', '').strip()
    if image and not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
        raise ValueError('invalid configured Runner image identity')
    return image


def input_digest(base, diff, visible, sealed):
    if not isinstance(base, str) or not re.fullmatch(r'(?:[a-f0-9]{40}|[a-f0-9]{64})', base):
        raise ValueError('immutable Runner base required')
    if not isinstance(diff, str):
        raise ValueError('Runner diff must be text')
    for suite in (visible, sealed):
        if not isinstance(suite, list) or any(not isinstance(t, dict) or not isinstance(t.get('code'), str) for t in suite):
            raise ValueError('Runner suite must contain code')
    return digest({'version': 1, 'base': base, 'diff': diff,
                   'visible': [t['code'] for t in visible],
                   'sealed': [{'code': t['code'], 'kind': t.get('kind', '')} for t in sealed]})


def result_digest(report):
    def counts(name):
        section = report[name]
        return {key: section.get(key) for key in ('pass', 'n', 'timed_out', 'exit_code')}
    return digest({'base': report['base'], 'hygiene': report.get('hygiene', []),
                   'visible': counts('visible'), 'heldout': counts('heldout'),
                   'heldout_kinds': report['heldout_kinds']})


def prepare(base, diff, visible, sealed):
    image = configured_image()
    if not image:
        return None  # Legacy executions cannot back canonical gates through this bridge.
    return {'version': 1, 'runner_image_digest': image,
            'input_sha256': input_digest(base, diff or '', visible, sealed)}


def attach(report, prepared):
    if prepared is not None:
        report['attestation'] = {**prepared, 'result_sha256': result_digest(report)}
    return report


def verify(report, base, diff, visible, sealed, expected_image=''):
    att = report.get('attestation')
    if not isinstance(att, dict) or set(att) != {'version', 'runner_image_digest', 'input_sha256', 'result_sha256'}:
        raise ValueError('Runner provenance metadata required')
    image = att.get('runner_image_digest')
    if (type(att.get('version')) is not int or att['version'] != 1
            or not isinstance(image, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', image)
            or expected_image and image != expected_image
            or report.get('base') != base
            or att.get('input_sha256') != input_digest(base, diff, visible, sealed)
            or att.get('result_sha256') != result_digest(report)):
        raise ValueError('Runner provenance differs from inputs, results or configured image')
    return att
