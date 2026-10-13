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

"""Tests for publish_target_configs.py."""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publish_target_configs as ptc  # pylint: disable=wrong-import-position
import spanner  # pylint: disable=wrong-import-position

CONFIG = """# CONFIG_OFF is not set
CONFIG_A=y
CONFIG_NAME="a=b"
VARIANT_X=1
HAS_TASK_FOO=1
CONFIG_VBOOT_FWID_VERSION="Google_Krabby.16838.0.0"
UNRELATED=1
"""
MANIFEST = json.dumps({
    'component_list': [
        {
            'component_name': 'ti,bq25710',
            'component_type': 'charger',
            'i2c': {
                'port': 1,
                'addr': '0x9'
            },
            'probe': 'gpio',
        },
        {
            'component_name': 'lonely',
            'component_type': 'tcpc',
            'usbc': {
                'port': 0
            },
        },
    ]
})


class ParseTest(unittest.TestCase):
  """Unit tests for config and component manifest parsers."""

  def test_symbols(self) -> None:
    self.assertEqual(
        ptc.parse_symbols(CONFIG),
        {
            'CONFIG_A': 'y',
            'CONFIG_NAME': '"a=b"',
            'VARIANT_X': '1',
            'HAS_TASK_FOO': '1',
        },
    )

  def test_components(self) -> None:
    self.assertEqual(
        ptc.parse_components(MANIFEST),
        [
            {
                'type': 'charger',
                'vendor': 'ti',
                'model': 'bq25710',
                'i2c_port': 1,
                'i2c_addr': '0x9',
                'usbc_port': None,
                'probe': 'gpio',
            },
            {
                'type': 'tcpc',
                'vendor': None,
                'model': 'lonely',
                'i2c_port': None,
                'i2c_addr': None,
                'usbc_port': 0,
                'probe': None,
            },
        ],
    )

  def test_components_bad_json(self) -> None:
    self.assertEqual(ptc.parse_components('{'), [])

  def test_digest_ignores_order_but_not_values(self) -> None:
    self.assertEqual(
        ptc.digest({
            'A': '1',
            'B': '2'
        }), ptc.digest({
            'B': '2',
            'A': '1'
        }))
    self.assertNotEqual(ptc.digest({'A': '1'}), ptc.digest({'A': '2'}))


class PublishTest(unittest.TestCase):
  """Unit tests for publishing target configs to Spanner."""

  def setUp(self) -> None:
    self.tmp = Path(tempfile.mkdtemp())
    self.addCleanup(shutil.rmtree, self.tmp)
    self.calls: list[tuple[str, dict[str, Any]]] = []
    self.known: list[str] = []
    patcher = mock.patch.object(spanner.Database, 'request',
                                side_effect=self.request)
    patcher.start()
    self.addCleanup(patcher.stop)

  def request(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
    self.calls.append((path, body))
    if path.endswith('/sessions'):
      return {'name': 'projects/p/instances/i/databases/d/sessions/s'}
    if path.endswith(':read'):
      return {'rows': [[config_hash] for config_hash in self.known]}
    return {}

  def write_file(self, name: str, content: str) -> str:
    path = self.tmp / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    return str(path)

  def data(
      self,
      configs: dict[str, str],
      components_text: str | None = None,
      name: str = 'krabby.EC.tar.bz2',
  ) -> dict[str, Any]:
    config_paths = {
        kind: self.write_file(f'{kind}.config', text)
        for kind, text in configs.items()
    }
    components_path = (
        self.write_file('components.json', components_text)
        if components_text is not None else None)
    return {
        'database':
            'build_metadata_staging',
        'build': {
            'id': 8,
            'builder': 'firmware-zephyr-postsubmit',
            'bucket': 'postsubmit',
            'number': 12,
            'start_time': '2026-10-09T01:02:03Z',
            'branch': 'snapshot',
            'commit': 'abc',
            'milestone': 157,
            'platform_version': '16838.0.0',
        },
        'targets': [{
            'platform': 'corsola',
            'target': 'krabby',
            'uri': f'gs://b/p/{name}',
            'configs': config_paths,
            'components_path': components_path,
        }],
    }

  def commits(self) -> list[list[str]]:
    return [[m['insertOrUpdate']['table']
             for m in body['mutations']]
            for path, body in self.calls
            if path.endswith(':commit')]

  def test_new_config_set(self) -> None:
    ptc.publish(
        self.data(
            {
                'ec-ro': 'CONFIG_A=y\n',
                'ec-rw': CONFIG
            },
            components_text=MANIFEST,
        ),
        'token',
    )

    self.assertEqual(
        self.commits(),
        [['ConfigSymbols'], ['ConfigSets'], ['Builds', 'BuildTargets']],
    )
    self.assertEqual(
        self.calls[0][0],
        'projects/firmware-bigquery/instances/firmware-metadata/databases/'
        'build_metadata_staging/sessions',
    )
    build, targets = self.calls[-1][1]['mutations']
    self.assertEqual(
        build['insertOrUpdate']['columns'],
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
    )
    self.assertEqual(
        build['insertOrUpdate']['values'],
        [[
            '8',
            'firmware-zephyr-postsubmit',
            'postsubmit',
            '12',
            '2026-10-09T01:02:03Z',
            'snapshot',
            'abc',
            '157',
            '16838.0.0',
            spanner.COMMIT_TIMESTAMP,
        ]],
    )
    self.assertEqual(
        targets['insertOrUpdate']['columns'],
        [
            'BuildId',
            'Platform',
            'Target',
            'Kind',
            'TarballUri',
            'ConfigHash',
            'Components',
        ],
    )
    rows = targets['insertOrUpdate']['values']
    self.assertEqual(
        [(row[3], row[5]) for row in rows],
        [
            ('ec-ro', ptc.digest({'CONFIG_A': 'y'})),
            ('ec-rw', ptc.digest(ptc.parse_symbols(CONFIG))),
        ],
    )

  def test_unknown_build_number_and_milestone_are_null(self) -> None:
    data = self.data({'ec-rw': CONFIG})
    data['build'].update(number=None, milestone=None)
    ptc.publish(data, 'token')
    row = self.calls[-1][1]['mutations'][0]['insertOrUpdate']['values'][0]
    self.assertEqual([row[3], row[7]], [None, None])

  def test_known_config_set_is_not_written_again(self) -> None:
    self.known = [ptc.digest(ptc.parse_symbols(CONFIG))]
    ptc.publish(self.data({'ec-rw': CONFIG}), 'token')
    self.assertEqual(self.commits(), [['Builds', 'BuildTargets']])

  def test_symbols_are_written_in_chunks(self) -> None:
    with mock.patch.object(spanner, 'MAX_ROWS_PER_COMMIT', 3):
      ptc.publish(self.data({'ec-rw': CONFIG}), 'token')
    self.assertEqual(
        self.commits(),
        [
            ['ConfigSymbols'],
            ['ConfigSymbols'],
            ['ConfigSets'],
            ['Builds', 'BuildTargets'],
        ],
    )

  def test_components_only(self) -> None:
    ptc.publish(self.data({}, components_text=MANIFEST), 'token')
    self.assertEqual(self.commits(), [['Builds', 'BuildTargets']])
    row = self.calls[-1][1]['mutations'][1]['insertOrUpdate']['values'][0]
    self.assertEqual(row[3], 'ec')
    self.assertIsNone(row[5])

  def test_ap_configs(self) -> None:
    ptc.publish(
        self.data(
            {
                'coreboot': 'CONFIG_A=y\n',
                'depthcharge': 'CONFIG_A=y\n',
                'libpayload': 'CONFIG_B=y\n',
            },
            name='krabby.16838.0.0.tar.bz2',
        ),
        'token',
    )

    self.assertEqual(
        self.commits(),
        [['ConfigSymbols'], ['ConfigSets'], ['Builds', 'BuildTargets']],
    )
    symbols = self.calls[2][1]['mutations'][0]['insertOrUpdate']['values']
    self.assertEqual(
        sorted(row[1:] for row in symbols),
        [['CONFIG_A', 'y'], ['CONFIG_B', 'y']],
    )
    rows = self.calls[-1][1]['mutations'][1]['insertOrUpdate']['values']
    self.assertEqual(
        {row[3]: (row[5], row[6]) for row in rows},
        {
            'coreboot': (ptc.digest({'CONFIG_A': 'y'}), None),
            'depthcharge': (ptc.digest({'CONFIG_A': 'y'}), None),
            'libpayload': (ptc.digest({'CONFIG_B': 'y'}), None),
        },
    )

  def test_nothing_found(self) -> None:
    ptc.publish(
        self.data({'ec': '# CONFIG_OFF is not set\n'}),
        'token',
    )
    self.assertEqual(self.calls, [])

  def test_main(self) -> None:
    token_file = self.write_file('token.txt', 'secret-token\n')
    input_file = self.write_file('input.json',
                                 json.dumps(self.data({'ec': 'CONFIG_A=y\n'})))
    ptc.main(['--token-file', token_file, '--input-json', input_file])
    self.assertEqual(
        self.commits(),
        [['ConfigSymbols'], ['ConfigSets'], ['Builds', 'BuildTargets']],
    )


if __name__ == '__main__':
  unittest.main()
