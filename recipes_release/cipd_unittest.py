#!/usr/bin/env vpython3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest.mock import call
from unittest.mock import MagicMock
from unittest.mock import patch

import cipd
import common
import test_util

CIPD_DESCRIBE_STDOUT = f'''Package:       {cipd.PACKAGE_NAME}
  Instance ID:   jSHBVU-ZzC8Pbi2hlc0r89wukZBQ9EYZKK7TX1zmboIC
  Registered by: user:infra-internal-recipe-bundler@chops-service-accounts.iam.gserviceaccount.com
  Registered at: 2022-09-23 13:11:22.569365 -0600 MDT
  Refs:
    prod
    release_2022/09/23-12
  Tags:
    git_revision:1114d30c71229c5cd470df15f863e9ddcfff6fb5'''

CIPD_RESOLVE_STDOUT = f'''Packages:
  {cipd.PACKAGE_NAME}:jSHBVU-ZzC8Pbi2hlc0r89wukZBQ9EYZKK7TX1zmboIC'''

EXPECTED_RECIPE_BUNDLE = cipd.PACKAGE_NAME

subprocess_stdout = test_util.subprocess_stdout
SUBPROCESS_KWARGS = test_util.SUBPROCESS_KWARGS


class CipdVersionToGitHashTest(unittest.TestCase):

  @patch('cipd.subprocess.run')
  def test_success_ref(self, mock_subprocess_run: MagicMock):
    mock_subprocess_run.return_value = subprocess_stdout(
        stdout=CIPD_DESCRIBE_STDOUT)

    expected_hash = common.GitHash('1114d30c71229c5cd470df15f863e9ddcfff6fb5')
    self.assertEqual(
        cipd.cipd_version_to_githash(common.CipdRef('prod')), expected_hash)

    mock_subprocess_run.assert_called_with(
        ['cipd', 'describe', '-version', 'prod', EXPECTED_RECIPE_BUNDLE],
        **SUBPROCESS_KWARGS)

  @patch('cipd.subprocess.run')
  def test_success_instance(self, mock_subprocess_run: MagicMock):
    mock_subprocess_run.return_value = subprocess_stdout(
        stdout=CIPD_DESCRIBE_STDOUT)

    expected_hash = common.GitHash('1114d30c71229c5cd470df15f863e9ddcfff6fb5')
    self.assertEqual(
        cipd.cipd_version_to_githash(
            common.CipdInstance(
                'jSHBVU-ZzC8Pbi2hlc0r89wukZBQ9EYZKK7TX1zmboIC')), expected_hash)

    mock_subprocess_run.assert_called_with([
        'cipd', 'describe', '-version',
        'jSHBVU-ZzC8Pbi2hlc0r89wukZBQ9EYZKK7TX1zmboIC', EXPECTED_RECIPE_BUNDLE
    ], **SUBPROCESS_KWARGS)

  @patch('cipd.subprocess.run')
  def test_fail_badstdout(self, mock_subprocess_run: MagicMock):
    mock_subprocess_run.return_value = subprocess_stdout(stdout='foo')

    with self.assertRaises(AssertionError):
      cipd.cipd_version_to_githash(common.CipdRef('prod'))

    mock_subprocess_run.assert_called_with(
        ['cipd', 'describe', '-version', 'prod', EXPECTED_RECIPE_BUNDLE],
        **SUBPROCESS_KWARGS)


class DetermineCipdAndGitTargetsTest(unittest.TestCase):

  @patch('cipd.subprocess.run')
  def test_success_instance(self, mock_subprocess_run: MagicMock):
    mock_subprocess_run.side_effect = [
        subprocess_stdout(CIPD_DESCRIBE_STDOUT),
        subprocess_stdout(CIPD_RESOLVE_STDOUT),
    ]
    self.assertEqual(cipd.determine_cipd_and_git_targets(),
                     ('jSHBVU-ZzC8Pbi2hlc0r89wukZBQ9EYZKK7TX1zmboIC',
                      '1114d30c71229c5cd470df15f863e9ddcfff6fb5'))
    mock_subprocess_run.assert_has_calls([
        call([
            'cipd', 'describe', '-version', 'refs/heads/main',
            EXPECTED_RECIPE_BUNDLE
        ], **SUBPROCESS_KWARGS),
        call([
            'cipd', 'resolve', '-version',
            'git_revision:1114d30c71229c5cd470df15f863e9ddcfff6fb5',
            EXPECTED_RECIPE_BUNDLE
        ], **SUBPROCESS_KWARGS)
    ])


if __name__ == '__main__':
  unittest.main()
