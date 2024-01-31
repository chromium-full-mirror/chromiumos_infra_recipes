# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine.recipe_api import StepFailure
from PB.chromiumos.branch import Branch

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_branch',
]



def RunSteps(api):
  download_path = api.path.mkdtemp(prefix='manifests-').join('download.xml')

  with api.assertions.assertRaises(StepFailure):
    # Bad version string.
    api.cros_branch.create_from_buildspec('foo', branch=None)

  with api.assertions.assertRaises(StepFailure):
    api.cros_branch.create_from_file(download_path, branch=None)
  with api.assertions.assertRaises(StepFailure):
    api.cros_branch.create_from_file(download_path,
                                     branch=Branch(type=Branch.UNSPECIFIED))

  with api.assertions.assertRaises(StepFailure):
    api.cros_branch.create_from_file(download_path,
                                     branch=Branch(type=Branch.CUSTOM))

  my_branch = Branch(name='my_branch')
  with api.assertions.assertRaises(StepFailure):
    api.cros_branch.rename(my_branch, None)
  with api.assertions.assertRaises(StepFailure):
    api.cros_branch.rename(Branch(), 'my_branch')

  with api.assertions.assertRaises(StepFailure):
    api.cros_branch.delete(Branch())


def GenTests(api):
  yield api.test('basic')
