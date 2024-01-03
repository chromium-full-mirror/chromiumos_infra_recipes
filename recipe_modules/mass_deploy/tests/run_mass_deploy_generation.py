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

PYTHON_VERSION_COMPATIBILITY = 'PY3'

# Reduced versions of the signing metadata from these two builds:
# https://logs.chromium.org/logs/chromeos/buildbucket/cr-buildbucket/8779438015707186865/+/u/get_signed_build_metadata/parse_metadata/signed_build_metadata
# https://logs.chromium.org/logs/chromeos/buildbucket/cr-buildbucket/8779172876182422209/+/u/get_signed_build_metadata/parse_metadata/signed_build_metadata

_METADATA_CANARY = {
    'gs://chromeos-releases/canary-channel/reven/15487.0.0/ChromeOS-recovery-R116-15487.0.0-reven.instructions':
        {
            'channel': 'canary',
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
    'gs://chromeos-releases/beta-channel/reven/15437.42.0/ChromeOS-recovery-R114-15437.42.0-reven.instructions':
        {
            'channel': 'beta',
            'outputs': {
                'chromeos_15437.42.0_reven_recovery_beta-channel_mp-v2.bin': {},
                'chromeos_15437.42.0_reven_recovery_beta-channel_mp-v2.bin.zip':
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
    'gs://chromeos-releases/stable-channel/reven/15437.42.0/ChromeOS-recovery-R114-15437.42.0-reven.instructions':
        {
            'channel': 'stable',
            'outputs': {
                'chromeos_15437.42.0_reven_recovery_stable-channel_mp-v2.bin': {
                },
                'chromeos_15437.42.0_reven_recovery_stable-channel_mp-v2.bin.zip':
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


def RunSteps(api):
  api.mass_deploy.run_mass_deploy_generation(api.properties['signing_metadata'])


def GenTests(api):

  def _gen_metadata(channels, outputs_override=None):
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

    if outputs_override:
      outputs = {key: {} for key in outputs_override}
      for value in result.values():
        value['outputs'] = outputs

    return result

  yield api.test(
      'basic',
      api.properties(signing_metadata=_gen_metadata(['beta', 'stable'])),
      api.post_check(post_process.MustRun,
                     'generate mass deploy builds.only run on stable builds'),
      api.post_check(post_process.MustRun,
                     'generate mass deploy builds.determine builder settings'),
      api.post_check(post_process.MustRun,
                     'generate mass deploy builds.schedule mass deploy build'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-stable',
      api.properties(signing_metadata=_gen_metadata(['canary', 'dev'])),
      api.post_check(post_process.MustRun,
                     'generate mass deploy builds.only run on stable builds'),
      api.post_check(post_process.DoesNotRun,
                     'generate mass deploy builds.determine builder settings'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-zip',
      api.properties(
          signing_metadata=_gen_metadata(['beta', 'stable'],
                                         outputs_override=['some.bin'])),
      api.post_check(post_process.MustRun,
                     'generate mass deploy builds.only run on stable builds'),
      api.post_check(post_process.StepFailure,
                     'generate mass deploy builds.determine builder settings'),
      api.post_process(post_process.DropExpectation), status='FAILURE')

  yield api.test(
      'two-zips',
      api.properties(
          signing_metadata=_gen_metadata(['beta', 'stable'], outputs_override=[
              'some.bin.zip', 'another.zip'
          ])),
      api.post_check(post_process.MustRun,
                     'generate mass deploy builds.only run on stable builds'),
      api.post_check(post_process.StepFailure,
                     'generate mass deploy builds.determine builder settings'),
      api.post_process(post_process.DropExpectation), status='FAILURE')

  yield api.test(
      'release',
      api.properties(signing_metadata=_gen_metadata(['beta', 'stable'])),
      api.post_check(post_process.StepSummaryEquals,
                     'generate mass deploy builds.schedule mass deploy build',
                     'scheduled release-mass-deploy'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'staging',
      api.properties(signing_metadata=_gen_metadata(['beta', 'stable'])),
      api.buildbucket.generic_build(bucket='staging'),
      api.post_check(post_process.StepSummaryEquals,
                     'generate mass deploy builds.schedule mass deploy build',
                     'scheduled staging-release-mass-deploy'),
      api.post_process(post_process.DropExpectation))
