# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to verify dlc_utils.get_dlc_artifacts."""

from recipe_engine import post_process
from PB.recipe_modules.chromeos.dlc_utils.tests.test import DlcUtilsTestProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'dlc_utils',
]


PROPERTIES = DlcUtilsTestProperties


def RunSteps(api, properties):
  api.path.mock_add_paths(api.path.cleanup_dir / 'artifacts/dlc/found/dlc.img')
  api.path.mock_add_paths(api.path.cleanup_dir / 'artifacts/dlc/found2/dlc.img')

  api.dlc_utils.artifacts_local_path = properties.dlc_path

  dlc_artifacts = api.dlc_utils.get_dlc_artifacts(
      'gs://chromeos-image-archive/brya-release/R108-15132.0.0/')

  api.assertions.assertEqual(
      len(properties.expected_artifacts), len(dlc_artifacts))
  for url, dlc_hash in properties.expected_artifacts.items():
    api.assertions.assertEqual(dlc_hash, dlc_artifacts[url]['hash'])


def GenTests(api):

  yield api.test(
      'success',
      api.properties(
          dlc_path='[CLEANUP]/artifacts/', expected_artifacts={
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/found/dlc.img':
                  'deadbeef',
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/found2/dlc.img':
                  'deadbeef'
          }),
      api.step_data(
          'Hash DLCs.Find DLCs.gsutil ls dlc', stdout=api.raw_io.output_text('''
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/found/dlc.img
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/found2/dlc.img
      '''), retcode=0),
      api.post_check(post_process.DoesNotRun, 'Hash DLCs.download GS file'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'local-failure',
      api.properties(
          dlc_path='[CLEANUP]/artifacts/', expected_artifacts={
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/missing/dlc.img':
                  'deadbeef',
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/found/dlc.img':
                  'deadbeef'
          }),
      api.step_data(
          'Hash DLCs.Find DLCs.gsutil ls dlc', stdout=api.raw_io.output_text('''
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/missing/dlc.img
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/found/dlc.img
      '''), retcode=0),
      # Downloads exactly one file.
      api.post_check(post_process.MustRun, 'Hash DLCs.download GS file'),
      api.post_check(post_process.DoesNotRun, 'Hash DLCs.download GS file (2)'),
      api.post_process(post_process.DropExpectation))
