# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process
from PB.chromiumos.branch import Branch
from PB.recipe_modules.chromeos.cros_branch.cros_branch import (
    CrosBranchProperties)

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_branch',
]


def RunSteps(api):
  download_path = api.path.mkdtemp(prefix='manifests-').join('download.xml')

  api.cros_branch.create_from_file(download_path,
                                   branch=Branch(type=Branch.RELEASE))

  api.cros_branch.create_from_file(
      download_path, branch=Branch(type=Branch.RELEASE),
      step_name="create branch from http://chromium.org/manifest.xml",
      push=True, force=True)

  branch = api.cros_branch.create_from_buildspec(
      'R89-13729.0.0',
      branch=Branch(type=Branch.RELEASE),
      step_name="create branch from buildspec",
      push=True,
      force=True,
  )
  api.assertions.assertEqual(branch, "release-R89-13729.B")

  api.cros_branch.create_from_file(
      download_path, branch=Branch(type=Branch.CUSTOM, name='mybranch',
                                   descriptor='nami'))

  my_branch = Branch(name='my_branch')
  api.cros_branch.rename(my_branch, 'branch_new_name')

  api.cros_branch.delete(my_branch)


TEST_STDOUT = """
2021/02/16 23:10:18.736295 No branch exists for version 13729.0.0. Continuing...
2021/02/16 23:10:18.744031 Creating branch: release-R89-13729.B
2021/02/16 23:10:19 Repairing manifest project chromiumos/manifest
"""


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(post_process.StepCommandContains,
                     'ensure branch_util.ensure_installed',
                     ['chromiumos/infra/test_planner latest']),
      api.step_data('create branch from buildspec',
                    stdout=api.raw_io.output(TEST_STDOUT)),
      api.post_check(
          post_process.StepCommandContains, 'create branch from buildspec',
          ['create', '--buildspec-manifest', '89/13729.0.0.xml', '--release']),
  )

  yield api.test(
      'with-ref',
      api.properties(
          **{"$chromeos/cros_branch": {
              "test_planner_cipd_ref": "foo"
          }}),
      api.step_data('create branch from buildspec',
                    stdout=api.raw_io.output(TEST_STDOUT)),
      api.post_check(post_process.StepCommandContains,
                     'ensure branch_util.ensure_installed',
                     ['chromiumos/infra/test_planner foo']),
  )
