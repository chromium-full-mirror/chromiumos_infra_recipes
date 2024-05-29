#!/usr/bin/env vpython3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for the `bb` module."""

import collections
import copy
import datetime
import json
from typing import Any, Dict, List
import unittest
from unittest import mock

import dataclasses

import bb
import common
import git
import staging_checks
import test_util

RECIPES_ANALYZE_OUTPUT = '''{
  "recipes": [
    "bar"
  ],
  "invalidRecipes": [],
  "error": ""
}'''


class GetAffectedRecipesTest(unittest.TestCase):

  @mock.patch('bb.json.dump')
  @mock.patch('bb.subprocess.run')
  @mock.patch('bb.tempfile.NamedTemporaryFile')
  def test_success(self, mock_tempfile: mock.MagicMock,
                   mock_subprocess_run: mock.MagicMock,
                   mock_dump: mock.MagicMock):
    mock_subprocess_run.side_effect = [
        test_util.subprocess_stdout('\n'.join(
            ['recipe_modules/util/api.py', 'recipes/bar.py'])),
        # ./recipes.py analyze fn writes to a file, no meaningful stdout.
        test_util.subprocess_stdout('...'),
    ]
    mock_tempfile.return_value.__enter__.return_value.read.return_value = RECIPES_ANALYZE_OUTPUT

    # Pass in the wrong order, make sure we're correctly determining the newest
    # and oldest commits.
    commits = [
        git.Commit(
            'abcde', '', '', '',
            datetime.datetime.fromisoformat(
                '2020-01-01T12:00:00+00:00').isoformat()),
        git.Commit(
            'zzzzz', '', 'update chromite-HEAD version', '',
            datetime.datetime.fromisoformat(
                '2020-01-02T12:00:00+00:00').isoformat()),
        git.Commit(
            '12345', '', '', '',
            datetime.datetime.fromisoformat(
                '2020-01-03T12:00:00+00:00').isoformat())
    ]
    all_recipes = ['foo', 'bar', 'baz']
    affected_recipes = bb.get_affected_recipes(commits, all_recipes)
    self.assertEqual(affected_recipes, ['bar'])

    mock_dump.assert_called_with(
        {
            'files': [
                'recipe_modules/util/api.py', 'recipes/bar.py',
            ],
            'recipes': ['bar', 'baz', 'foo'],
        }, mock.ANY)
    mock_subprocess_run.assert_has_calls([
        mock.call(['git', 'diff', '--name-only', '12345', 'abcde~'],
                  **test_util.SUBPROCESS_KWARGS)
    ])


class GetBuilderRecipeTest(unittest.TestCase):

  @mock.patch('bb.subprocess.run')
  def test_success(self, mock_subprocess_run: mock.MagicMock):
    mock_subprocess_run.return_value = test_util.subprocess_stdout(
        json.dumps({
            'buildbucket': {
                'bbagent_args': {
                    'build': {
                        'input': {
                            'properties': {
                                'recipe': 'annealing',
                            }
                        }
                    }
                }
            }
        }))
    self.assertEqual(
        bb.get_builder_recipe('chromeos/staging/staging-Annealing'),
        'annealing')
    mock_subprocess_run.assert_called_with(
        ['led', 'get-builder', 'chromeos/staging/staging-Annealing'],
        **test_util.SUBPROCESS_KWARGS)


def _build_data(cipd_version: common.CipdVersion, bbid: int = 800000,
                status: str = 'SUCCESS',
                create_time: str = '2023-07-12T18:30:03.433569345Z') -> Dict:
  return {
      'id': bbid,
      'status': status,
      'createTime': create_time,
      'infra': {
          'buildbucket': {
              'agent': {
                  'output': {
                      'resolvedData': {
                          'kitchen-checkout': {
                              'cipd': {
                                  'specs': [{
                                      'package':
                                          'infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes',
                                      'version':
                                          cipd_version
                                  }]
                              }
                          }
                      }
                  }
              }
          }
      }
  }


class GetBuildToCipdVersionTest(unittest.TestCase):

  def setUp(self):
    self.build_data = _build_data(
        cipd_version='aWEyswgHmB8rkXG1y4T3bazO8Ursei5wgNgvt0YJzIMC')

  def test_success(self):
    self.assertEqual(
        bb.build_to_cipd_version(self.build_data),
        'aWEyswgHmB8rkXG1y4T3bazO8Ursei5wgNgvt0YJzIMC')

  def test_success_nospecs(self):
    build_data = copy.deepcopy(self.build_data)
    del build_data['infra']['buildbucket']['agent']['output']['resolvedData'][
        'kitchen-checkout']['cipd']['specs']

    self.assertIsNone(bb.build_to_cipd_version(build_data))

  def test_success_wrongspecs(self):
    build_data = copy.deepcopy(self.build_data)
    build_data['infra']['buildbucket']['agent']['output']['resolvedData'][
        'kitchen-checkout']['cipd']['specs'] = [{
            'package': 'foo',
            'version': 'bar'
        }]

    self.assertIsNone(bb.build_to_cipd_version(build_data))


class GetBuilderLinkTest(unittest.TestCase):

  def test_success(self):
    self.assertEqual(
        bb.get_builder_link('chromeos/staging/staging-Annealing'),
        'https://ci.chromium.org/p/chromeos/builders/staging/staging-Annealing')

  def test_fail(self):
    with self.assertRaises(ValueError):
      bb.get_builder_link('staging-Annealing')


class ReturnBuildersForRegexTest(unittest.TestCase):

  @mock.patch('bb.subprocess.run')
  def test_success(self, mock_subprocess_run: mock.MagicMock):
    mock_subprocess_run.return_value = test_util.subprocess_stdout('\n'.join([
        'chromeos/staging/staging-release-R108-15183.B-android-vm-rvc-uprev-orchestrator',
        'chromeos/staging/staging-release-R108-15183.B-cq-orchestrator',
        'chromeos/staging/staging-release-R108-15183.B-orchestrator',
        'chromeos/staging/staging-release-R112-15359.B-android-vm-rvc-uprev-orchestrator',
        'chromeos/staging/staging-release-R108-15183.B-orchestrator',
        'chromeos/staging/staging-release-R113-15393.B-android-vm-rvc-uprev-orchestrator',
        'chromeos/staging/staging-release-R113-15393.B-orchestrator',
        'chromeos/staging/staging-arm64-generic-snapshot',
        'chromeos/staging/staging-arm64-generic-cq',
        'chromeos/staging/staging-arm64-generic-public-main'
    ]))

    builders = bb.return_builders_for_regex(
        'chromeos', 'staging',
        r'staging-release-R(?P<milestone>\d+)-\d+\.B-orchestrator')
    self.assertEqual(builders, [
        'chromeos/staging/staging-release-R113-15393.B-orchestrator',
    ])

    mock_subprocess_run.assert_called_with(
        ('bb', 'builders', 'chromeos/staging'), **test_util.SUBPROCESS_KWARGS)


class BuildsTest(unittest.TestCase):

  @mock.patch('bb.return_builders_for_regex')
  @mock.patch('bb.subprocess.run')
  def test_initialize(self, mock_subprocess_run: mock.MagicMock,
                      mock_return_builders_for_regex: mock.MagicMock):

    # Changes are not in chronological order.
    changes = [
        git.Commit('30000', '', '', '', '2020-01-03T12:00:00+00:00'),
        git.Commit('10000', '', '', '', '2020-01-01T12:00:00+00:00'),
        git.Commit('20000', '', 'update chromite-HEAD version', '',
                   '2020-01-02T12:00:00+00:00'),
    ]

    # These are the staging builders we care about.
    checks = [
        staging_checks.StagingReCheck('chromeos', 'staging', 'staging-Foo'),
        staging_checks.StagingReCheck('chromeos', 'staging', 'staging-Bar'),
        staging_checks.StagingReCheck('chromeos', 'staging', 'staging-Baz'),
    ]

    def return_builders_for_regex(project: str, bucket: str,
                                  regex: str) -> List[str]:
      del project, bucket  # Unused.
      return {
          'staging-Foo': ['chromeos/staging/staging-Foo'],
          'staging-Bar': ['chromeos/staging/staging-Bar'],
          'staging-Baz': ['chromeos/staging/staging-Baz'],
      }[regex]

    mock_return_builders_for_regex.side_effect = return_builders_for_regex

    all_builds = bb.Builds()
    all_builds.initialize(checks, changes)
    for builder in ['staging-Foo', 'staging-Bar', 'staging-Baz']:
      mock_subprocess_run.assert_any_call(
          [
              'bb',
              'ls',
              '-json',
              '-predicate',
              # Check that the oldest change is used.
              '{"builder": {"project": "chromeos", "bucket": "staging", "builder": "%s"}, "status": "ENDED_MASK", "create_time": {"start_time": "2020-01-01T12:00:00+00:00"}}'
              % builder,
              '-fields',
              'id,status,create_time,infra,summary_markdown,cancellation_markdown',
          ],
          **test_util.SUBPROCESS_KWARGS)

  @mock.patch('bb.cipd.cipd_version_to_githash')
  def test_success(self, mock_cipd_version_to_githash: mock.MagicMock):
    build_data = {
        'chromeos/staging/staging-foo': [
            _build_data('YYY', bbid=1000, status='SUCCESS',
                        create_time='2020-01-03T13:00:00.000000000Z'),
            _build_data('YYY', bbid=1001, status='SUCCESS',
                        create_time='2020-01-03T14:00:00.000000000Z'),
            _build_data('YYY', bbid=1002, status='SUCCESS',
                        create_time='2020-01-03T15:00:00.000000000Z'),
            _build_data('XXX', bbid=1003, status='SUCCESS',
                        create_time='2020-01-03T16:00:00.000000000Z'),
            _build_data('XXX', bbid=1004, status='INFRA_FAILURE',
                        create_time='2020-01-03T17:00:00.000000000Z'),
            _build_data('XXX', bbid=1005, status='SUCCESS',
                        create_time='2020-01-03T18:00:00.000000000Z'),
        ]
    }
    all_builds = bb.Builds()
    all_builds.initialize_with_test_data(build_data)

    def cipd_version_to_githash(version: common.CipdVersion):
      return {
          'XXX': '30000',
          'YYY': '19500',
      }[version]

    mock_cipd_version_to_githash.side_effect = cipd_version_to_githash

    def is_older_than_mock(change_hash):
      return lambda other_hash: int(other_hash) >= int(change_hash)

    change = git.Commit('20000', '', '', '', '2020-01-03T13:30:00+00:00')
    change.is_older_than = is_older_than_mock(change.hash)

    self.assertEqual(
        all_builds.get_builds_after('chromeos/staging/staging-foo', change),
        build_data['chromeos/staging/staging-foo'][1:])
    self.assertEqual(
        all_builds.get_builds_containing('chromeos/staging/staging-foo',
                                         change),
        build_data['chromeos/staging/staging-foo'][3:])

    change = git.Commit('40000', '', '', '', '2020-01-03T15:30:00+00:00')
    change.is_older_than = is_older_than_mock(change.hash)

    self.assertEqual(
        all_builds.get_builds_after('chromeos/staging/staging-foo', change),
        build_data['chromeos/staging/staging-foo'][3:])
    self.assertEqual(
        all_builds.get_builds_containing('chromeos/staging/staging-foo',
                                         change), [])

    change = git.Commit('40000', '', '', '', '2020-01-03T18:30:00+00:00')
    change.is_older_than = is_older_than_mock(change.hash)
    self.assertEqual(
        all_builds.get_builds_after('chromeos/staging/staging-foo', change), [])
    self.assertEqual(
        all_builds.get_builds_containing('chromeos/staging/staging-foo',
                                         change), [])


class CheckRecentBuildStatusesTest(unittest.TestCase):

  @mock.patch('bb.cipd.cipd_version_to_githash')
  @mock.patch('bb.subprocess.run')
  def do_test(self, build_data: List[Dict[str, Any]], expected_ret: bool,
              ok_fewer: bool, mock_subprocess_run: mock.MagicMock,
              mock_cipd_version_to_githash: mock.MagicMock):
    mock_subprocess_run.return_value = test_util.subprocess_stdout('\n'.join(
        [json.dumps(build) for build in build_data]))

    def cipd_version_to_githash(version: common.CipdVersion):
      return {
          'XXX': '30000',
          'YYY': '20500',
          'ZZZ': '12000',
      }[version]

    mock_cipd_version_to_githash.side_effect = cipd_version_to_githash

    # Changes are not in chronological order.
    changes = [
        git.Commit('10000', '', '', '', '2020-01-01T12:00:00+00:00'),
        git.Commit('30000', '', '', '', '2020-01-03T12:00:00+00:00'),
        git.Commit('20000', '', 'update chromite-HEAD version', '',
                   '2020-01-02T12:00:00+00:00'),
    ]

    def is_older_than_mock(change_hash):
      return lambda other_hash: int(other_hash) >= int(change_hash)

    for i, _ in enumerate(changes):
      changes[i].is_older_than = is_older_than_mock(changes[i].hash)

    all_builds = bb.Builds()
    all_builds.initialize_with_test_data({
        'chromeos/staging/staging-foo': build_data,
    })
    self.assertEqual(
        bb.check_recent_build_statuses(
            all_builds,
            'chromeos/staging/staging-foo',
            # Basic exemption exempting any build with bbid 1003.
            [lambda build: build['id'] == 1003],
            changes,
            5,
            ok_fewer=ok_fewer,
        )[0],
        expected_ret)

  def test_all_success(self):
    build_data = [
        _build_data('YYY', bbid=1000, status='SUCCESS',
                    create_time='2020-01-03T13:00:00.000000000Z'),
        _build_data('XXX', bbid=1001, status='SUCCESS',
                    create_time='2020-01-03T14:00:00.000000000Z'),
        _build_data('XXX', bbid=1002, status='SUCCESS',
                    create_time='2020-01-03T15:00:00.000000000Z'),
        _build_data('XXX', bbid=1003, status='FAILURE',
                    create_time='2020-01-03T16:00:00.000000000Z'),
        _build_data('XXX', bbid=1004, status='SUCCESS',
                    create_time='2020-01-03T17:00:00.000000000Z'),
        _build_data('XXX', bbid=1005, status='SUCCESS',
                    create_time='2020-01-03T18:00:00.000000000Z'),
        # First five builds were okay so this won't be looked at.
        _build_data('XXX', bbid=1006, status='INFRA_FAILURE',
                    create_time='2020-01-03T19:00:00.000000000Z'),
    ]
    self.do_test(build_data, False, False)  # pylint: disable=no-value-for-parameter

  def test_insufficient(self):
    # We don't have enough builds, so we fail even though they're all success.
    build_data = [
        # YYY predates the most recent change, so even though we have
        # 5 builds only 4 are applicable.
        _build_data('YYY', bbid=1000, status='SUCCESS',
                    create_time='2020-01-03T13:00:00.000000000Z'),
        _build_data('XXX', bbid=1001, status='SUCCESS',
                    create_time='2020-01-03T14:00:00.000000000Z'),
        _build_data('XXX', bbid=1002, status='SUCCESS',
                    create_time='2020-01-03T15:00:00.000000000Z'),
        _build_data('XXX', bbid=1003, status='SUCCESS',
                    create_time='2020-01-03T16:00:00.000000000Z'),
        _build_data('XXX', bbid=1004, status='SUCCESS',
                    create_time='2020-01-03T17:00:00.000000000Z'),
    ]
    self.do_test(build_data, True, False)  # pylint: disable=no-value-for-parameter

  def test_ok_fewer(self):
    # We don't have enough builds, but ok_fewer is True, so we pass.
    build_data = [
        # YYY predates the most recent change, so even though we have
        # 5 builds only 4 are applicable.
        _build_data('YYY', bbid=1000, status='SUCCESS',
                    create_time='2020-01-03T13:00:00.000000000Z'),
        _build_data('XXX', bbid=1001, status='SUCCESS',
                    create_time='2020-01-03T14:00:00.000000000Z'),
        _build_data('XXX', bbid=1002, status='SUCCESS',
                    create_time='2020-01-03T15:00:00.000000000Z'),
        _build_data('XXX', bbid=1003, status='SUCCESS',
                    create_time='2020-01-03T16:00:00.000000000Z'),
        _build_data('XXX', bbid=1004, status='SUCCESS',
                    create_time='2020-01-03T17:00:00.000000000Z'),
    ]
    self.do_test(build_data, False, True)  # pylint: disable=no-value-for-parameter

  def test_failure(self):
    # We don't have enough consecutive successes.
    build_data = [
        _build_data('YYY', bbid=1000, status='SUCCESS',
                    create_time='2020-01-03T13:00:00.000000000Z'),
        _build_data('XXX', bbid=1001, status='SUCCESS',
                    create_time='2020-01-03T14:00:00.000000000Z'),
        _build_data('XXX', bbid=1002, status='SUCCESS',
                    create_time='2020-01-03T15:00:00.000000000Z'),
        _build_data('XXX', bbid=1003, status='SUCCESS',
                    create_time='2020-01-03T16:00:00.000000000Z'),
        _build_data('XXX', bbid=1004, status='INFRA_FAILURE',
                    create_time='2020-01-03T17:00:00.000000000Z'),
        _build_data('XXX', bbid=1005, status='SUCCESS',
                    create_time='2020-01-03T18:00:00.000000000Z'),
    ]
    self.do_test(build_data, True, False)  # pylint: disable=no-value-for-parameter


class DetermineMaximumCoveredInstanceTest(unittest.TestCase):

  @dataclasses.dataclass(frozen=True)
  class TestConfig:
    changes: List[git.Commit]
    build_data: Dict[str, List[Dict]]
    cipd_instances_to_git_hashes: Dict[str, str]
    affected_recipes: Dict[str, List[str]]
    enforce_success: bool

  @mock.patch('bb.get_affected_recipes')
  @mock.patch('bb.get_builder_recipe')
  @mock.patch('bb.cipd.cipd_version_to_githash')
  @mock.patch('bb.return_builders_for_regex')
  @mock.patch('bb._bb_ls')
  def do_test(self, config: TestConfig, mock_subprocess_run: mock.MagicMock,
              mock_return_builders_for_regex: mock.MagicMock,
              mock_cipd_version_to_githash: mock.MagicMock,
              mock_get_builder_recipe: mock.MagicMock,
              mock_get_affected_recipes: mock.MagicMock):
    changes = config.changes
    build_data = config.build_data
    cipd_instances_to_git_hashes = config.cipd_instances_to_git_hashes
    affected_recipes = config.affected_recipes
    enforce_success = config.enforce_success

    def get_builder_recipe(builder: str) -> str:
      return {
          'chromeos/staging/staging-Foo': 'foo',
          'chromeos/staging/staging-Bar': 'bar',
          'chromeos/staging/staging-Baz': 'baz',
          'chromeos/staging/staging-NewBuilder': 'new_builder',
      }[builder]

    mock_get_builder_recipe.side_effect = get_builder_recipe

    # Generate changes.
    def is_older_than_mock(change_hash):
      return lambda other_hash: int(other_hash) >= int(change_hash)

    for i, _ in enumerate(changes):
      changes[i].is_older_than = is_older_than_mock(changes[i].hash)
      changes[i].get_cipd_instance = mock.MagicMock(
          return_value=changes[i].hash)

    # Some changes affect recipes.
    def get_affected_recipes(changes: List[git.Commit], *_) -> List[str]:
      return affected_recipes[changes[0].hash]

    mock_get_affected_recipes.side_effect = get_affected_recipes

    # These are the staging builders we care about.
    checks = [
        staging_checks.StagingReCheck('chromeos', 'staging', 'staging-Foo'),
        staging_checks.StagingReCheck('chromeos', 'staging', 'staging-Bar'),
        staging_checks.StagingReCheck('chromeos', 'staging', 'staging-Baz'),
        staging_checks.StagingReCheck('chromeos', 'staging',
                                      'staging-NewBuilder'),
    ]

    def return_builders_for_regex(project: str, bucket: str,
                                  regex: str) -> List[str]:
      del project, bucket  # Unused.
      return {
          'staging-Foo': ['chromeos/staging/staging-Foo'],
          'staging-Bar': ['chromeos/staging/staging-Bar'],
          'staging-Baz': ['chromeos/staging/staging-Baz'],
          'staging-NewBuilder': ['chromeos/staging/staging-NewBuilder'],
      }[regex]

    mock_return_builders_for_regex.side_effect = return_builders_for_regex

    # These are the build results we get.
    def bb_ls(*args):
      for builder, data in build_data.items():
        if builder in ' '.join(args):
          return data
      return []

    mock_subprocess_run.side_effect = bb_ls

    def cipd_version_to_githash(version: common.CipdVersion):
      return cipd_instances_to_git_hashes[version]

    mock_cipd_version_to_githash.side_effect = cipd_version_to_githash

    all_builds = bb.Builds()
    all_builds.initialize_with_test_data(build_data)
    cipd_instance, _ = bb.determine_maximum_covered_instance(
        all_builds, changes, checks, enforce_success=enforce_success)
    return cipd_instance

  def test_success(self):
    """Test determine_maximum_covered_instance with a releasable instance."""
    changes = {}
    for i in range(10):
      change_hash = str(10000 + i * 10)
      commit_timestamp = datetime.datetime.fromisoformat(
          '2020-01-01T12:00:00+00:00') + datetime.timedelta(hours=i)
      changes[change_hash] = git.Commit(change_hash, '', '', '',
                                        commit_timestamp.isoformat())

    changes['10070'].message = 'update chromite-HEAD version'
    changes['10060'].message = 'Roll recipe dependencies (trivial).'

    build_results = {
        'chromeos/staging/staging-Foo': [
            _build_data('XXX'),
            _build_data('XXX'),
            _build_data('XXX'),
            _build_data('XXX'),
            _build_data('XXX'),
            _build_data('YYY'),
            _build_data('ZZZ'),
        ],
        'chromeos/staging/staging-Bar': [
            _build_data('XXX'),
            _build_data('XXX'),
            _build_data('XXX'),
            _build_data('YYY'),
            _build_data('YYY'),
            _build_data('YYY'),
            _build_data('ZZZ'),
        ],
        # < 5 results so should get ignored.
        'chromeos/staging/staging-NewBuilder': [_build_data('XXX')]
    }
    instance_to_hash = {
        'XXX': '10095',
        'YYY': '10060',
        'ZZZ': '9000',
    }

    # In this test, most changes affect every recipe.
    affected_recipes = {
        '10060': [],
        # 10070 is a chromite pin uprev. affected_recipes will inject
        # cros_build_api as a dependency and use that to determine affected
        # recipes. In this case, declare `bar` to be relevant.
        '10070': ['bar'],
    }
    affected_recipes_dict = collections.defaultdict(
        lambda: ['foo', 'bar', 'baz'], affected_recipes)

    instance = self.do_test(  # pylint: disable=no-value-for-parameter
        self.TestConfig(
            list(changes.values()), build_results, instance_to_hash,
            affected_recipes_dict, enforce_success=False))
    # 10060 is releasable but is a trivial commit.
    self.assertEqual(instance, '10050')

  def test_success_limited_builds(self):
    """Test determine_maximum_covered_instance with limited builds available."""
    changes = {}
    for i in range(10):
      change_hash = str(10000 + i * 10)
      commit_timestamp = datetime.datetime.fromisoformat(
          '2020-01-01T12:00:00+00:00') + datetime.timedelta(hours=i)
      changes[change_hash] = git.Commit(change_hash, '', '', '',
                                        commit_timestamp.isoformat())

    build_results = {
        'chromeos/staging/staging-Foo': [
            _build_data('XXX'),
            _build_data('XXX'),
            _build_data('XXX'),
            _build_data('YYY'),
            _build_data('YYY'),
        ],
    }
    instance_to_hash = {
        'XXX': '10095',
        'YYY': '10060',
        'ZZZ': '9000',
    }
    affected_recipes_dict = collections.defaultdict(lambda: ['foo'])

    instance = self.do_test(  # pylint: disable=no-value-for-parameter
        self.TestConfig(
            list(changes.values()), build_results, instance_to_hash,
            affected_recipes_dict, enforce_success=False))
    self.assertEqual(instance, '10060')

  def test_success_nocovered(self):
    """Test determine_maximum_covered_instance with no covered instances."""
    changes = []
    for i in range(10):
      change_hash = str(10000 + i * 10)
      commit_timestamp = datetime.datetime.fromisoformat(
          '2020-01-01T12:00:00+00:00') + datetime.timedelta(hours=i)
      changes.append(
          git.Commit(change_hash, '', '', '', commit_timestamp.isoformat()))

    build_results = {
        'chromeos/staging/staging-Foo': [
            _build_data('XXX'),
            _build_data('XXX'),
            _build_data('XXX'),
            _build_data('XXX'),
            _build_data('ZZZ'),
            _build_data('ZZZ'),
            _build_data('ZZZ'),
        ],
        'chromeos/staging/staging-Bar': [
            _build_data('XXX'),
            _build_data('XXX'),
            _build_data('XXX'),
            _build_data('YYY'),
            _build_data('YYY'),
            _build_data('YYY'),
            _build_data('ZZZ'),
        ],
        # < 5 results so should get ignored.
        'chromeos/staging/staging-NewBuilder': [_build_data('XXX')]
    }
    instance_to_hash = {
        'XXX': '10095',
        'YYY': '10060',
        'ZZZ': '9000',
    }

    affected_recipes_dict = collections.defaultdict(
        lambda: ['foo', 'bar', 'baz'])

    instance = self.do_test(  # pylint: disable=no-value-for-parameter
        self.TestConfig(changes, build_results, instance_to_hash,
                        affected_recipes_dict, enforce_success=False))
    # ZZZ is older than all changes and there are only four builds
    # since ZZZ for staging-Foo.
    self.assertIsNone(instance)

  def test_success_enforce_success(self):
    """Test determine_maximum_covered_instance with enforce_success enabled."""
    changes = []
    for i in range(10):
      change_hash = str(10000 + i * 10)
      commit_timestamp = datetime.datetime.fromisoformat(
          '2020-01-01T12:00:00+00:00') + datetime.timedelta(hours=i)
      changes.append(
          git.Commit(change_hash, '', '', '', commit_timestamp.isoformat()))

    build_results = {
        'chromeos/staging/staging-Foo': [
            _build_data('ZZZ', bbid=1000, status='SUCCESS',
                        create_time='2020-01-01T13:30:00.000000000Z'),
            _build_data('ZZZ', bbid=1001, status='SUCCESS',
                        create_time='2020-01-01T14:30:00.000000000Z'),
            _build_data('ZZZ', bbid=1002, status='SUCCESS',
                        create_time='2020-01-01T15:30:00.000000000Z'),
            _build_data('XXX', bbid=1003, status='SUCCESS',
                        create_time='2020-01-01T16:30:00.000000000Z'),
            _build_data('XXX', bbid=1004, status='FAILURE',
                        create_time='2020-01-01T17:30:00.000000000Z'),
            _build_data('XXX', bbid=1005, status='SUCCESS',
                        create_time='2020-01-01T18:30:00.000000000Z'),
            _build_data('XXX', bbid=1006, status='SUCCESS',
                        create_time='2020-01-01T19:30:00.000000000Z'),
            _build_data('XXX', bbid=1007, status='SUCCESS',
                        create_time='2020-01-01T20:30:00.000000000Z'),
            _build_data('XXX', bbid=1008, status='SUCCESS',
                        create_time='2020-01-01T20:30:00.000000000Z'),
            _build_data('XXX', bbid=1009, status='SUCCESS',
                        create_time='2020-01-01T20:30:00.000000000Z'),
        ],
    }
    instance_to_hash = {
        'XXX': '10095',
        'YYY': '10060',
        'ZZZ': '9000',
    }

    affected_recipes_dict = collections.defaultdict(lambda: ['foo'])

    instance = self.do_test(  # pylint: disable=no-value-for-parameter
        self.TestConfig(changes, build_results, instance_to_hash,
                        affected_recipes_dict, enforce_success=True))
    # The first 5 foo builds for changes[3] are [1003, 1007], containing 1004 (failure).
    # The first 5 foo builds for changes[6] are [1005, 1009], which should be OK.
    # changes[7] only has 4 builds.
    self.assertEqual(instance, '10060')


if __name__ == '__main__':
  unittest.main()
