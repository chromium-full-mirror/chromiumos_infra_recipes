# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests collect_and_report_sbom call."""

from recipe_engine import post_process

DEPS = [
    'cros_ssci',
    'recipe_engine/buildbucket',
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/path',
    'recipe_engine/step',
]


def RunSteps(api):
  out_path = api.path.mkdtemp('cros_ssci') / 'out.json'
  api.cros_ssci.generate_sbom(out_path)


def GenTests(api):
  yield api.test(
      'report_sbom',
      api.post_check(post_process.StatusSuccess),
  ) + api.buildbucket.ci_build(project="chromeos", builder="amd64")
