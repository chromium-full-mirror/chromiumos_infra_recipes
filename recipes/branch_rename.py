# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Renames a branch using `cros branch rename`."""

from PB.chromiumos.branch import Branch
from PB.recipes.chromeos.branch_rename import RenameBranchProperties
import os

DEPS = [
    'recipe_engine/context',
    'recipe_engine/properties',
    'cros_branch',
    'cros_source',
]

PROPERTIES = RenameBranchProperties


def RunSteps(api, properties):
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context(), api.context(
      cwd=api.cros_source.workspace_path):
    api.cros_branch.rename(
        properties.branch,
        properties.new_name,
        push=properties.push,
        force=properties.force)


def GenTests(api):
  yield (api.test('valid') + api.properties(
      manifest_url='http://www.chromium.org/manifest.xml',
      push=True,
      force=True,
      branch={'name': 'my_branch'},
      new_name='renamed_branch'))

  yield (api.test('missing-branch-name') + api.properties(
      manifest_url='http://www.chromium.org/manifest.xml',
      new_name='renamed_branch') + api.expect_exception('ValueError'))

  yield (api.test('missing-new-branch-name') + api.properties(
      manifest_url='http://www.chromium.org/manifest.xml',
      branch={'name': 'my_branch'}) + api.expect_exception('ValueError'))
