# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from recipe_engine import post_process

from PB.chromiumos.common import Channel
from PB.recipe_modules.chromeos.cros_release.examples.get_release_qs_account import TestProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/time',
    'cros_infra_config',
    'cros_release',
    'cros_source',
    'cros_version',
    'orch_menu',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = TestProperties


def RunSteps(api, properties):
  config = api.cros_infra_config.config
  branch_name = config.orchestrator.gitiles_commit.ref[len('refs/heads/'):]
  api.cros_source.test_api.manifest_branch = branch_name

  qs_account = api.cros_release.get_release_qs_account()
  api.assertions.assertEqual(qs_account, properties.expected_qs_account)


def GenTests(api):

  def no_schedule(test_name, channels, expected_qs_account):
    return api.orch_menu.test(
        test_name,
        api.properties(
            **{
                'expected_qs_account': expected_qs_account,
                '$chromeos/cros_release': {
                    'channels': channels,
                }
            }),
        api.step_data(
            'determine release testing priority.fetch schedule.json.gsutil cat',
            retcode=1),
        api.post_process(post_process.PropertyEquals, 'dynamic_qs_account',
                         expected_qs_account),
        api.post_process(post_process.DropExpectation),
        builder='release-main-orchestrator')

  yield no_schedule('no-schedule-stable',
                    [Channel.CHANNEL_STABLE, Channel.CHANNEL_BETA],
                    'release_high_prio')
  yield no_schedule('no-schedule-beta', [Channel.CHANNEL_BETA],
                    'release_med_prio')
  yield no_schedule('no-schedule-dev',
                    [Channel.CHANNEL_CANARY, Channel.CHANNEL_DEV],
                    'release_low_prio')

  yield api.orch_menu.test(
      'malformatted-schedule',
      api.properties(
          **{
              'expected_qs_account': 'release_low_prio',
              '$chromeos/cros_release': {
                  'channels': [Channel.CHANNEL_DEV],
              }
          }),
      api.step_data(
          'determine release testing priority.fetch schedule.json.gsutil cat',
          stdout=api.raw_io.output('{bad-json')),
      api.post_process(post_process.PropertyEquals, 'dynamic_qs_account',
                       'release_low_prio'),
      api.post_process(post_process.DropExpectation),
      builder='release-main-orchestrator')

  # Seed time to Tuesday, April 25, 2023 9:42:34 AM GMT-06:00.
  SEED_TIME = 1682437354

  test_data = json.dumps({
      '2023-04-20': {
          'primary': '111',
      },
      '2023-04-21': {
          'primary': '113',
          'secondary': '112',
      },
  })
  yield api.orch_menu.test(
      'out-of-date-schedule',
      api.properties(
          **{
              'expected_qs_account': 'release_high_prio',
              '$chromeos/cros_release': {
                  # Should fall back to high prio based on the stable channel.
                  'channels': [Channel.CHANNEL_STABLE],
              }
          }),
      api.time.seed(SEED_TIME),
      api.cros_version.workspace_version('R112-12345.0.0'),
      api.step_data(
          'determine release testing priority.fetch schedule.json.gsutil cat',
          stdout=api.raw_io.output(test_data)),
      api.post_process(post_process.PropertyEquals, 'dynamic_qs_account',
                       'release_high_prio'),
      api.post_process(post_process.DropExpectation),
      builder='release-main-orchestrator')

  test_data = json.dumps({
      '2023-04-24': {
          'primary': '111',
      },
      '2023-04-25': {
          'primary': '113',
          'secondary': '112',
      },
  })

  def schedule_test(name, version, expected_qs_account):
    return api.orch_menu.test(
        name,
        api.properties(
            **{
                'expected_qs_account': expected_qs_account,
                '$chromeos/cros_release': {
                    # Default behavior will fall back to high prio based on
                    # the stable channel, but that will get overridden based
                    # on the value of `version`.
                    'channels': [Channel.CHANNEL_STABLE],
                }
            }),
        api.time.seed(SEED_TIME),
        api.cros_version.workspace_version(version),
        api.step_data(
            'determine release testing priority.fetch schedule.json.gsutil cat',
            stdout=api.raw_io.output(test_data)),
        api.post_process(post_process.PropertyEquals, 'dynamic_qs_account',
                         expected_qs_account),
        api.post_process(post_process.DropExpectation),
        builder='release-main-orchestrator')

  yield schedule_test('primary', 'R113-12345.0.0', 'release_high_prio')
  yield schedule_test('secondary', 'R112-12345.0.0', 'release_med_prio')
  yield schedule_test('non-prio', 'R114-12345.0.0', 'release_low_prio')

  yield api.orch_menu.test(
      'stabilize-branch',
      api.properties(
          **{
              # Should get low priority based on the stabilize branch.
              'expected_qs_account': 'release_low_prio',
              '$chromeos/cros_release': {
                  # We would expect this to fallback to high prio based on the
                  # stable channel, but this behavior should get overridden by
                  # the fact that we're a stabilize branch..
                  'channels': [Channel.CHANNEL_STABLE],
              }
          }),
      api.time.seed(SEED_TIME),
      # Should get "primary" based on the milestone.
      api.cros_version.workspace_version('R113-12345.0.0'),
      api.step_data(
          'determine release testing priority.fetch schedule.json.gsutil cat',
          stdout=api.raw_io.output(test_data)),
      api.post_process(post_process.PropertyEquals, 'dynamic_qs_account',
                       'release_low_prio'),
      api.post_process(post_process.DropExpectation),
      builder='release-stabilize-15185.B-orchestrator')
