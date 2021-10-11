# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for creating a new ChromeOS branch."""

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'cros_branch',
    'cros_release_config',
    'cros_source',
    'easy',
    'workspace_util',
]

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

from PB.chromiumos.branch import Branch
from PB.recipes.chromeos.brancher import BrancherProperties

PROPERTIES = BrancherProperties


def RunSteps(api, properties):
  with api.step.nest('validate properties'):
    if not properties.source_version:
      raise StepFailure("source_version required")
    if properties.branch_info.type not in [Branch.RELEASE, Branch.STABILIZE]:
      raise StepFailure("unsupported branch type: {}".format(
          properties.branch_info.type))
    branch_type = properties.branch_info.type

  # Create branch.
  with api.step.nest('create branch') as presentation:
    branch_name = api.cros_branch.create_from_buildspec(
        properties.source_version, branch=properties.branch_info,
        push=properties.branch_util_push, force=properties.branch_util_force)
    if not branch_name:
      raise StepFailure("branch name could not be parsed from branch_util")
    presentation.step_text = "Created branch {}".format(branch_name)
    api.easy.set_properties_step(branch_name=branch_name)

  if branch_type == Branch.RELEASE:
    with api.workspace_util.setup_workspace():
      api.cros_source.ensure_synced_cache(projects=[
          api.cros_release_config.LEGACY_CONFIG_PROJECT,
          api.cros_release_config.CONFIG_PROJECT
      ])

      api.cros_release_config.update_config(branch_name)


def GenTests(api):
  TEST_STDOUT = """
2021/02/16 23:10:18.736295 No branch exists for version 13729.0.0. Continuing...
2021/02/16 23:10:18.744031 Creating branch: release-R89-13729.B
2021/02/16 23:10:19 Repairing manifest project chromiumos/manifest
"""

  yield api.test(
      'release-branch',
      api.step_data(
          'create branch.'
          'create branch from buildspec manifest 89/13729.0.0.xml',
          stdout=api.raw_io.output(TEST_STDOUT)),
      api.properties(
          BrancherProperties(source_version='R89-13729.0.0',
                             branch_info=Branch(type=Branch.RELEASE))),
      api.post_check(
          post_process.StepCommandContains, 'create branch.'
          'create branch from buildspec manifest 89/13729.0.0.xml',
          ['create', '--buildspec-manifest', '89/13729.0.0.xml', '--release']),
  )

  yield api.test(
      'stabilize-branch-descriptor',
      api.step_data(
          'create branch'
          '.create branch from buildspec manifest 89/13729.0.0.xml',
          stdout=api.raw_io.output(TEST_STDOUT)),
      api.properties(
          BrancherProperties(
              source_version='R89-13729.0.0',
              branch_info=Branch(type=Branch.STABILIZE,
                                 name='this should not be used anywhere',
                                 descriptor="foo"))),
      api.post_check(
          post_process.StepCommandContains, 'create branch.'
          'create branch from buildspec manifest 89/13729.0.0.xml', [
              'create', '--buildspec-manifest', '89/13729.0.0.xml',
              '--stabilize', '--descriptor', 'foo'
          ]),
  )

  yield api.test(
      'no-source-version',
      api.properties(
          BrancherProperties(branch_info=Branch(type=Branch.RELEASE))),
      api.post_check(post_process.StepFailure, 'validate properties'),
  )

  yield api.test(
      'bad-branch-type',
      api.properties(
          BrancherProperties(source_version='R89-13729.0.0',
                             branch_info=Branch(type=Branch.FACTORY))),
      api.post_check(post_process.StepFailure, 'validate properties'),
  )

  yield api.test(
      'bad-branch_util-run',
      api.properties(
          BrancherProperties(source_version='R89-13729.0.0',
                             branch_info=Branch(type=Branch.RELEASE))),
      api.post_check(post_process.StepFailure, 'create branch'),
  )
