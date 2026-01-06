# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests generate_sbom and upload_sbom."""

from recipe_engine import post_process

DEPS = [
    'cros_ssci',
    'test_util',
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/path',
    'recipe_engine/step',
]


def RunSteps(api):
  dlc_spdx = api.path.mkdtemp('cros_ssci_test') / 'test-dlc-spdx.json'
  api.cros_ssci.generate_dlc_sbom("test-dlc", dlc_spdx)


def GenTests(api):
  yield api.test(
      'report_sbom',
      api.test_util.test_child_build(
          'kukui',
          builder_name='kukui-release-main',
          git_repo='https://chrome-internal.googlesource.com/chromeos/manifest-internal',
      ).build,
      api.post_check(post_process.StatusSuccess),
  )
