#!/usr/bin/env vpython3
# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# [VPYTHON:BEGIN]
# python_version: "3.11"
# wheel: <
#   name: "infra/python/wheels/requests-py3"
#   version: "version:2.31.0"
# >
# wheel: <
#   name: "infra/python/wheels/urllib3-py2_py3"
#   version: "version:1.26.6"
# >
# wheel: <
#   name: "infra/python/wheels/certifi-py2_py3"
#   version: "version:2021.5.30"
# >
# wheel: <
#   name: "infra/python/wheels/charset_normalizer-py3"
#   version: "version:2.0.4"
# >
# wheel: <
#   name: "infra/python/wheels/idna-py2_py3"
#   version: "version:2.10"
# >
# [VPYTHON:END]

"""Records the per-target firmware configs of one build in Cloud Spanner.

For every target in the input JSON, reads the exported Kconfig and Devicetree
component files and writes them to the build metadata database (schema.sql,
b/571108483).

A target keeps the same config from one build to the next, so config sets are
content addressed: the symbols of a set are written once, and every build only
adds one small BuildTargets row per config of a target that points at its set.

The input JSON has these keys:
  database: 'build_metadata' or 'build_metadata_staging'.
  build: id, builder, bucket, number, start_time, branch, commit, milestone and
    platform_version of the build. The branch and the commit are those of the
    manifest that it synced. The number and the milestone may be null.
  targets: a list of dicts with platform, target, uri (where the target tarball
    was uploaded), configs ({kind: path} of exported Kconfig files) and
    components_path (path to exported component_manifest.json or null).
"""

import argparse
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

import spanner

PROJECT = 'firmware-bigquery'
INSTANCE = 'firmware-metadata'

SYMBOL_RE = re.compile(r'^((?:CONFIG|VARIANT|HAS_TASK)_[A-Za-z0-9_]+)=(.*)$')
# The version of the build. Left in, it would give the config of every AP target
# a new set in every build.
BUILD_VERSION_SYMBOL = 'CONFIG_VBOOT_FWID_VERSION'


def parse_symbols(text: str) -> dict[str, str]:
  """Returns {symbol: value} for the enabled symbols of a Kconfig dump."""
  symbols: dict[str, str] = {}
  for line in text.splitlines():
    match = SYMBOL_RE.match(line.strip())
    if match:
      symbols[match.group(1)] = match.group(2)
  symbols.pop(BUILD_VERSION_SYMBOL, None)
  return symbols


def parse_components(text: str) -> list[dict[str, Any]]:
  """Returns the components of a Zephyr component_manifest.json."""
  try:
    manifest = json.loads(text)
  except ValueError:
    return []
  components: list[dict[str, Any]] = []
  for item in manifest.get('component_list', []):
    i2c = item.get('i2c') or {}
    usbc = item.get('usbc') or {}
    name = item.get('component_name') or ''
    vendor, comma, model = name.partition(',')
    if not comma:
      vendor, model = None, name or None
    components.append({
        'type': item.get('component_type'),
        'vendor': vendor,
        'model': model,
        'i2c_port': i2c.get('port'),
        'i2c_addr': i2c.get('addr'),
        'usbc_port': usbc.get('port'),
        'probe': item.get('probe'),
    })
  return components


def read_target(
    target: Mapping[str, Any],
) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
  """Returns ({kind: symbols}, components) read from a target's files."""
  configs: dict[str, dict[str, str]] = {}
  for kind, path in sorted((target.get('configs') or {}).items()):
    symbols = parse_symbols(
        Path(path).read_text(encoding='utf-8', errors='replace'))
    if symbols:
      configs[kind] = symbols
  components: list[dict[str, Any]] = []
  components_path = target.get('components_path')
  if components_path:
    components = parse_components(
        Path(components_path).read_text(encoding='utf-8', errors='replace'))
  return configs, components


def digest(symbols: Mapping[str, str]) -> str:
  """Returns the id of a config set, which does not depend on symbol order."""
  text = ''.join(f'{k}={v}\n' for k, v in sorted(symbols.items()))
  return hashlib.sha256(text.encode('utf-8')).hexdigest()


def publish(data: Mapping[str, Any], token: str) -> None:
  """Writes the configs of data['targets'] to data['database']."""
  build = data['build']
  config_sets: dict[str, dict[str, str]] = {}
  target_rows: dict[tuple[str, str, str], list[Any]] = {}
  for target in data['targets']:
    configs, components = read_target(target)
    if not configs and not components:
      print(f'No configs for {target["target"]}')
      continue
    # A target with only components, such as an ISH, still gets a row.
    for kind, symbols in (configs or {'ec': {}}).items():
      config_hash = digest(symbols) if symbols else None
      if config_hash:
        config_sets[config_hash] = symbols
      target_rows[target['platform'], target['target'], kind] = [
          str(build['id']),
          target['platform'],
          target['target'],
          kind,
          target.get('uri'),
          config_hash,
          json.dumps(components) if components else None,
      ]
  if not target_rows:
    print('Nothing to publish.')
    return

  db = spanner.Database(PROJECT, INSTANCE, data['database'], token)
  known = db.read_keys('ConfigSets', 'ConfigHash', list(config_sets))
  new_sets = sorted(set(config_sets) - known)

  symbol_rows = [[config_hash, name, value]
                 for config_hash in new_sets
                 for name, value in sorted(config_sets[config_hash].items())]
  db.commit_rows('ConfigSymbols', ['ConfigHash', 'Name', 'Value'], symbol_rows)
  # The set is written last, so a ConfigSets row means all of its symbols are
  # stored and a build that failed half way is repaired by the next one.
  if new_sets:
    db.commit(
        spanner.upsert(
            'ConfigSets',
            ['ConfigHash', 'SymbolCount', 'WrittenAt'],
            [[
                config_hash,
                str(len(config_sets[config_hash])),
                spanner.COMMIT_TIMESTAMP,
            ] for config_hash in new_sets],
        ))

  # One commit, so a build is recorded completely or not at all.
  db.commit(
      spanner.upsert(
          'Builds',
          [
              'BuildId',
              'Builder',
              'Bucket',
              'BuildNumber',
              'StartTime',
              'Branch',
              'ManifestCommitId',
              'Milestone',
              'PlatformVersion',
              'WrittenAt',
          ],
          [[
              str(build['id']),
              build['builder'],
              build['bucket'],
              spanner.int64(build['number']),
              build['start_time'],
              build['branch'],
              build['commit'],
              spanner.int64(build['milestone']),
              build['platform_version'],
              spanner.COMMIT_TIMESTAMP,
          ]],
      ),
      spanner.upsert(
          'BuildTargets',
          [
              'BuildId',
              'Platform',
              'Target',
              'Kind',
              'TarballUri',
              'ConfigHash',
              'Components',
          ],
          list(target_rows.values()),
      ),
  )
  print(f'Published {len(target_rows)} target configs of build {build["id"]} '
        f'to {data["database"]}: {len(new_sets)} new config sets '
        f'({len(symbol_rows)} symbols).')


def get_parser() -> argparse.ArgumentParser:
  """Builds the argument parser."""
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
      '--token-file',
      required=True,
      type=Path,
      help='Path to file containing the OAuth2 access token.',
  )
  parser.add_argument(
      '--input-json',
      required=True,
      type=Path,
      help='Path to the input JSON file.',
  )
  return parser


def main(argv: list[str] | None = None) -> int | None:
  """Parses CLI flags and publishes target configs to Cloud Spanner."""
  parser = get_parser()
  opts = parser.parse_args(argv)
  token = opts.token_file.read_text(encoding='utf-8').strip()
  data = json.loads(opts.input_json.read_bytes())
  publish(data, token)


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
