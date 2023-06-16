#!/usr/bin/env vpython3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy
import json
import unittest
from unittest import mock
from unittest.mock import call
from unittest.mock import MagicMock
from unittest.mock import patch

import bb
import git
import test_util

RECIPES_ANALYZE_OUTPUT = """{
  "recipes": [
    "bar"
  ],
  "invalidRecipes": [],
  "error": ""
}"""


class GetAffectedRecipesTest(unittest.TestCase):

  @patch('bb.json.dump')
  @patch('bb.subprocess.run')
  @patch('bb.tempfile.NamedTemporaryFile')
  def test_success(self, mock_tempfile: MagicMock,
                   mock_subprocess_run: MagicMock, mock_dump: MagicMock):
    mock_subprocess_run.side_effect = [
        test_util.subprocess_stdout('\n'.join(
            ['recipe_modules/util/api.py', 'recipes/bar.py'])),
        # ./recipes.py analyze fn writes to a file, no meaningful stdout.
        test_util.subprocess_stdout('...'),
    ]
    mock_tempfile.return_value.__enter__.return_value.read.return_value = RECIPES_ANALYZE_OUTPUT

    newest_commit = git.Commit('12345', '', '', '')
    oldest_commit = git.Commit('abcde', '', '', '')
    all_recipes = ['foo', 'bar', 'baz']
    affected_recipes = bb.get_affected_recipes(newest_commit, oldest_commit,
                                               all_recipes)
    self.assertEqual(affected_recipes, ['bar'])

    mock_dump.assert_called_with(
        {
            'files': ['recipe_modules/util/api.py', 'recipes/bar.py'],
            'recipes': ['bar', 'baz', 'foo'],
        }, mock.ANY)
    mock_subprocess_run.assert_has_calls([
        call(['git', 'diff', '--name-only', '12345', 'abcde~'],
             **test_util.SUBPROCESS_KWARGS)
    ])


class GetBuilderRecipeTest(unittest.TestCase):

  @patch('bb.subprocess.run')
  def test_success(self, mock_subprocess_run: MagicMock):
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


class GetBuildToCipdVersionTest(unittest.TestCase):

  def setUp(self):
    self.build_data = {
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
                                            'aWEyswgHmB8rkXG1y4T3bazO8Ursei5wgNgvt0YJzIMC'
                                    }]
                                }
                            }
                        }
                    }
                }
            }
        }
    }

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

  @patch('bb.subprocess.run')
  def test_success(self, mock_subprocess_run: MagicMock):
    mock_subprocess_run.return_value = test_util.subprocess_stdout('\n'.join([
        'chromeos/staging/staging-release-R108-15183.B-android-vm-rvc-uprev-orchestrator',
        'chromeos/staging/staging-release-R108-15183.B-cq-orchestrator',
        'chromeos/staging/staging-release-R108-15183.B-orchestrator',
        'chromeos/staging/staging-release-R112-15359.B-android-vm-rvc-uprev-orchestrator',
        'chromeos/staging/staging-release-R108-15183.B-orchestrator',
        'chromeos/staging/staging-release-R113-15393.B-android-vm-rvc-uprev-orchestrator',
        'chromeos/staging/staging-release-R113-15393.B-orchestrator',
        'chromeos/staging/staging-arm64-generic-postsubmit',
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


if __name__ == '__main__':
  unittest.main()
