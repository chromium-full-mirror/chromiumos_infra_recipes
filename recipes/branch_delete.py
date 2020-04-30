# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Deletes a branch using `cros branch delete`."""

from PB.chromiumos.branch import Branch
from PB.recipes.chromeos.branch_delete import DeleteBranchProperties
import os

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'cros_branch',
    'cros_source',
]

PROPERTIES = DeleteBranchProperties


def RunSteps(api, properties):
  api.cros_branch.delete(
      properties.branch_info,
      push=properties.push,
      force=properties.force)


def GenTests(api):
  yield api.test(
      'valid',
      api.properties(manifest_url='http://www.chromium.org/manifest.xml',
                     push=True,
                     force=True,
                     branch_info={'name': 'my_branch'}),
  )

  yield api.test(
      'missing-branch-name',
      api.properties(manifest_url='http://www.chromium.org/manifest.xml'),
      api.expect_exception('ValueError'),
  )
