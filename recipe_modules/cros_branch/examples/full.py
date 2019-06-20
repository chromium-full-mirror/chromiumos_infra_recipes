# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.branch import Branch

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_branch',
]


def RunSteps(api):
  download_path = api.path.mkdtemp(prefix='manifests-').join('download.xml')

  api.cros_branch.create_from_file(
      download_path, branch=Branch(type=Branch.RELEASE))
  api.cros_branch.create_from_file(
      download_path,
      branch=Branch(type=Branch.RELEASE),
      step_name="create branch from http://chromium.org/manifest.xml",
      push=True,
      force=True)
  api.cros_branch.create_from_file(
      download_path, branch=Branch(type=Branch.RELEASE), root='~/chromiumos/')

  with api.assertions.assertRaises(ValueError):
    api.cros_branch.create_from_file(download_path, branch=None)
  with api.assertions.assertRaises(ValueError):
    api.cros_branch.create_from_file(
        download_path, branch=Branch(type=Branch.UNSPECIFIED))

  api.cros_branch.create_from_file(
      download_path,
      branch=Branch(type=Branch.CUSTOM, name='mybranch', descriptor='nami'))
  with api.assertions.assertRaises(ValueError):
    api.cros_branch.create_from_file(
        download_path, branch=Branch(type=Branch.CUSTOM))

  my_branch = Branch(name='my_branch')
  api.cros_branch.rename(my_branch, 'branch_new_name')
  with api.assertions.assertRaises(ValueError):
    api.cros_branch.rename(my_branch, None)
  with api.assertions.assertRaises(ValueError):
    api.cros_branch.rename(Branch(), 'branch_new_name')

  api.cros_branch.delete(my_branch)
  with api.assertions.assertRaises(ValueError):
    api.cros_branch.delete(Branch())


def GenTests(api):
  yield api.test('basic')
