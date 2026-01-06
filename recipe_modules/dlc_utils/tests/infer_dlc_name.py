# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to verify dlc_utils.get_dlcs_in_path."""

from recipe_engine import post_process
from PB.recipe_modules.chromeos.dlc_utils.tests.test import DlcUtilsTestProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'dlc_utils',
]

PROPERTIES = DlcUtilsTestProperties


def RunSteps(api, properties):
  cases = (
      ('/b/s/artifacts/dlc/sample-dlc/package/dlc.img', 'sample-dlc'),
      ('/b/s/artifacts/dlc-scaling/handwriting-am/package/dlc.img',
       'handwriting-am'),
      ('/random-path/file.bin', 'random-path-file.bin'),
  )
  for dlc_path, expected_dlc_name in cases:
    api.assertions.assertEqual(expected_dlc_name,
                               api.dlc_utils.infer_dlc_name(dlc_path))


def GenTests(api):

  yield api.test(
      'infer_dlc_name',
      api.properties(
          **
          {'$chromeos/dlc_utils': {
              'dlc_directories': ['dlc', 'dlc-scaling']
          }}), api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation))
