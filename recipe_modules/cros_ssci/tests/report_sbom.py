# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests generate_sbom and upload_sbom."""

from recipe_engine import post_process

DEPS = [
    'cros_ssci',
    'test_util',
    'recipe_engine/buildbucket',
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/path',
    'recipe_engine/step',
]


def RunSteps(api):
  result = api.cros_ssci.generate_and_upload_sbom()
  api.assertions.assertRegexpMatches(
      result.gs_url,
      'gs://chromeos-releases-test/kukui-release-main/R[^/]+/baseline-sbom.spdx.json',
  )


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
