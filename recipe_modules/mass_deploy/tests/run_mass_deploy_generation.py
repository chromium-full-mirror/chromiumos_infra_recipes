# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for run_mass_deploy_generation."""

from copy import deepcopy

from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'mass_deploy',
]


# Reduced versions of the signing metadata from these two builds:
# https://logs.chromium.org/logs/chromeos/buildbucket/cr-buildbucket/8779438015707186865/+/u/get_signed_build_metadata/parse_metadata/signed_build_metadata
# https://logs.chromium.org/logs/chromeos/buildbucket/cr-buildbucket/8779172876182422209/+/u/get_signed_build_metadata/parse_metadata/signed_build_metadata

_METADATA_CANARY = {
    'gs://chromeos-releases/canary-channel/reven/15487.0.0/ChromeOS-recovery-R116-15487.0.0-reven.instructions':
        {
            'channel': 'canary',
            'type': 'recovery',
            'outputs': {
                'chromeos_15487.0.0_reven_recovery_canary-channel_mp-v2.bin': {
                },
                'chromeos_15487.0.0_reven_recovery_canary-channel_mp-v2.bin.zip':
                    {}
            },
            'release_directory': 'canary-channel/reven/15487.0.0',
            'version': {
                'full': 'R116-15487.0.0',
                'milestone': '116',
                'platform': '15487.0.0'
            }
        }
}

_METADATA_DEV = {
    'gs://chromeos-releases/dev-channel/reven/15487.0.0/ChromeOS-recovery-R116-15487.0.0-reven.instructions':
        {
            'channel': 'dev',
            'type': 'recovery',
            'outputs': {
                'chromeos_15487.0.0_reven_recovery_dev-channel_mp-v2.bin': {},
                'chromeos_15487.0.0_reven_recovery_dev-channel_mp-v2.bin.zip': {
                }
            },
            'release_directory': 'dev-channel/reven/15487.0.0',
            'version': {
                'full': 'R116-15487.0.0',
                'milestone': '116',
                'platform': '15487.0.0'
            }
        }
}

_METADATA_BETA = {
    'gs://chromeos-releases/beta-channel/reven/15437.42.0/ChromeOS-recovery-R116-15437.42.0-reven.instructions':
        {
            'channel': 'beta',
            'outputs': {
                'chromeos_15487.0.0_reven_recovery_beta-channel_mp-v2.bin': {},
                'chromeos_15487.0.0_reven_recovery_beta-channel_mp-v2.bin.zip':
                    {}
            },
            'release_directory': 'beta-channel/reven/15437.42.0',
            'version': {
                'full': 'R116-15487.0.0',
                'milestone': '116',
                'platform': '15487.0.0'
            }
        }
}

_METADATA_STABLE = {
    'gs://chromeos-releases/stable-channel/reven/15437.42.0/ChromeOS-recovery-R116-15487.0.0-reven.instructions':
        {
            'channel': 'stable',
            'type': 'recovery',
            'outputs': {
                'chromeos_15487.0.0.0_reven_recovery_stable-channel_mp-v2.bin':
                    {},
                'chromeos_15487.0.0_reven_recovery_stable-channel_mp-v2.bin.zip':
                    {}
            },
            'release_directory': 'stable-channel/reven/15437.42.0',
            'version': {
                'full': 'R116-15487.0.0',
                'milestone': '116',
                'platform': '15487.0.0'
            }
        }
}

_METADATA_FLEXOR = {
    'gs://chromeos-releases/stable-channel/reven/15437.42.0/ChromeOS-flexor-R116-15487.0.0-reven.instructions':
        {
            'channel': 'stable',
            'type': 'uefi-kernel',
            'outputs': {
                'flexor_15487.0.0_reven_stable-channel.bin': {},
            },
            'release_directory': 'stable-channel/reven/15437.42.0',
            'version': {
                'full': 'R116-15487.0.0',
                'milestone': '116',
                'platform': '15487.0.0'
            }
        }
}

_METADATA_LTC = {
    'gs://chromeos-releases/ltc-channel/reven/15437.42.0/ChromeOS-recovery-R116-15487.0.0-reven.instructions':
        {
            'channel': 'ltc',
            'type': 'recovery',
            'outputs': {
                'chromeos_15487.0.0.0_reven_recovery_ltc-channel_mp-v2.bin': {},
                'chromeos_15487.0.0_reven_recovery_ltc-channel_mp-v2.bin.zip': {
                }
            },
            'release_directory': 'ltc-channel/reven/15437.42.0',
            'version': {
                'full': 'R116-15487.0.0',
                'milestone': '116',
                'platform': '15487.0.0'
            }
        }
}

_METADATA_LTS = {
    'gs://chromeos-releases/lts-channel/reven/15437.42.0/ChromeOS-recovery-R116-15487.0.0-reven.instructions':
        {
            'channel': 'lts',
            'type': 'recovery',
            'outputs': {
                'chromeos_15487.0.0.0_reven_recovery_lts-channel_mp-v2.bin': {},
                'chromeos_15487.0.0_reven_recovery_lts-channel_mp-v2.bin.zip': {
                }
            },
            'release_directory': 'lts-channel/reven/15437.42.0',
            'version': {
                'full': 'R116-15487.0.0',
                'milestone': '116',
                'platform': '15487.0.0'
            }
        }
}

def RunSteps(api):
  api.mass_deploy.run_mass_deploy_generation(api.properties['signing_metadata'])


def GenTests(api):

  def _any_log_contains(check, step_odict, steps, log_name,
                        expected_substrings):
    """Assert that each expected substring occurs in the log of at least one step

    This lets us test output of steps that appear multiple times.
    """
    # Collect all logs we want to examine.
    logs = [step_odict[step].logs[log_name] for step in steps]

    for expected in expected_substrings:
      check(any(expected in log for log in logs))

  def _gen_metadata(channels, outputs_override=None, include_flexor=False):
    """Piece together test data"""
    result = {}
    if 'canary' in channels:
      result.update(deepcopy(_METADATA_CANARY))
    if 'dev' in channels:
      result.update(deepcopy(_METADATA_DEV))
    if 'beta' in channels:
      result.update(deepcopy(_METADATA_BETA))
    if 'stable' in channels:
      result.update(deepcopy(_METADATA_STABLE))
    if 'ltc' in channels:
      result.update(deepcopy(_METADATA_LTC))
    if 'lts' in channels:
      result.update(deepcopy(_METADATA_LTS))

    if outputs_override:
      outputs = {key: {} for key in outputs_override}
      for value in result.values():
        value['outputs'] = outputs

    if include_flexor:
      result.update(deepcopy(_METADATA_FLEXOR))

    return result

  yield api.test(
      'normal-release',
      api.properties(signing_metadata=_gen_metadata(['beta', 'stable'])),
      api.post_check(
          post_process.MustRun,
          'generate mass deploy builds.only run on LTC, LTS or stable builds'),
      api.post_check(post_process.MustRun,
                     'generate mass deploy builds.determine builder settings'),
      api.post_check(
          post_process.MustRun,
          'generate mass deploy builds.schedule mass deploy build(s)'),
      api.post_check(
          post_process.MustRun,
          'generate mass deploy builds.schedule mass deploy build(s).buildbucket.schedule'
      ), api.post_process(post_process.DropExpectation))

  yield api.test(
      'multiple-valid-builds',
      api.properties(signing_metadata=_gen_metadata(['ltc', 'lts'])),
      api.post_check(
          post_process.MustRun,
          'generate mass deploy builds.only run on LTC, LTS or stable builds'),
      api.post_check(post_process.MustRun,
                     'generate mass deploy builds.determine builder settings'),
      api.post_check(
          post_process.MustRun,
          'generate mass deploy builds.schedule mass deploy build(s)'),
      # Check that multiple builds are triggered,
      # and that each channel appears in at least one build.
      api.post_check(
          post_process.MustRun,
          'generate mass deploy builds.schedule mass deploy build(s).buildbucket.schedule'
      ),
      api.post_check(
          post_process.MustRun,
          'generate mass deploy builds.schedule mass deploy build(s).buildbucket.schedule (2)'
      ),
      api.post_check(_any_log_contains, (
          'generate mass deploy builds.schedule mass deploy build(s).buildbucket.schedule',
          'generate mass deploy builds.schedule mass deploy build(s).buildbucket.schedule (2)',
      ), "request", ('ltc-channel', 'lts-channel')),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-valid-build',
      api.properties(signing_metadata=_gen_metadata(['canary', 'dev'])),
      api.post_check(
          post_process.MustRun,
          'generate mass deploy builds.only run on LTC, LTS or stable builds'),
      api.post_check(post_process.DoesNotRun,
                     'generate mass deploy builds.determine builder settings'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-zip',
      api.properties(
          signing_metadata=_gen_metadata(['beta', 'lts'],
                                         outputs_override=['some.bin'])),
      api.post_check(
          post_process.MustRun,
          'generate mass deploy builds.only run on LTC, LTS or stable builds'),
      api.post_check(post_process.StepFailure,
                     'generate mass deploy builds.determine builder settings'),
      api.post_process(post_process.DropExpectation), status='FAILURE')

  yield api.test(
      'two-zips',
      api.properties(
          signing_metadata=_gen_metadata(['beta', 'lts'], outputs_override=[
              'some.bin.zip', 'another.zip'
          ])),
      api.post_check(
          post_process.MustRun,
          'generate mass deploy builds.only run on LTC, LTS or stable builds'),
      api.post_check(post_process.StepFailure,
                     'generate mass deploy builds.determine builder settings'),
      api.post_process(post_process.DropExpectation), status='FAILURE')

  yield api.test(
      'staging',
      api.properties(signing_metadata=_gen_metadata(['beta', 'lts'])),
      api.buildbucket.generic_build(bucket='staging'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'flexor-present-along-with-flex-release-build',
      api.properties(
          signing_metadata=_gen_metadata(['stable'], include_flexor=True)),
      api.post_check(
          post_process.MustRun,
          'generate mass deploy builds.only run on LTC, LTS or stable builds'),
      api.post_check(post_process.MustRun,
                     'generate mass deploy builds.determine builder settings'),
      api.post_check(
          post_process.MustRun,
          'generate mass deploy builds.schedule mass deploy build(s)'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'do-nothing-if-only-flexor-is-present',
      api.properties(signing_metadata=_gen_metadata([], include_flexor=True)),
      api.post_check(
          post_process.MustRun,
          'generate mass deploy builds.only run on LTC, LTS or stable builds'),
      api.post_check(post_process.DoesNotRun,
                     'generate mass deploy builds.determine builder settings'),
      api.post_process(post_process.DropExpectation))
