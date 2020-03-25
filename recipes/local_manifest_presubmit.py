# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Runs the presubmit for a project with checkout per local manifest."""

import contextlib

from recipe_engine import post_process

from PB.project_mgmt.project import LocalManifest
from PB.recipes.chromeos.local_manifest_presubmit import (
    LocalManifestPresubmitProperties)

PROPERTIES = LocalManifestPresubmitProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'depot_tools/presubmit',
    'cros_source',
    'git',
    'repo',
    'workspace_util',
]


def RunSteps(api, properties):
  if not properties.project:
    raise ValueError('The project must be specified.')

  if not properties.manifest_groups:
    raise ValueError('At least one manifest group must be specified.')

  if not api.buildbucket.build.input.gerrit_changes:
    raise ValueError('At least one gerrit_change must be specified.')

  local_manifest = None
  if (properties.local_manifest.repo_url and
      properties.local_manifest.manifest_path):
    local_manifest = api.repo.LocalManifest(
        repo=properties.local_manifest.repo_url,
        path=properties.local_manifest.manifest_path)

  with api.context(infra_steps=True), \
      api.workspace_util.sync_to_manifest_groups(
          manifest_groups=properties.manifest_groups,
          local_manifest=local_manifest,
          cache_path_override=api.cros_source.workspace_path):
    api.workspace_util.apply_changes(api.buildbucket.build.input.gerrit_changes,
                                     only_checked_out_projects=True)

    project = api.repo.project_info(properties.project)
    workspace_path = api.cros_source.workspace_path
    project_path = workspace_path.join(project.path)

    with api.step.nest('prepare and execute presubmit'), \
        api.context(cwd=project_path):
      # Several checks require that we have an upstream tracking branch.
      # This requires us to have a branch, which we don't yet have.
      # Create the "__presubmit" branch, run the check, and then delete
      # it.
      # A refspec can't be used to set upstream, so extract the branch.
      branch = api.git.extract_branch(project.branch, 'master')
      api.step('setup', ['git', 'checkout', '-b', '__presubmit'])
      api.step('set tracking', [
          'git', 'branch', '--set-upstream-to',
          '%s/%s' % (project.remote, branch)])

      # infra_steps set in context take precedence over infra_step passed
      # to a step, so we make a new context here.
      with api.context(infra_steps=False):
        # TODO: catch the exception and produce a better failure.
        api.presubmit()


def GenTests(api):

  def project_config_cq_build(api):
    """Returns a sample buildbucket project config cq build"""
    return api.buildbucket.try_build(
        project='chromeos',
        bucket='testprogram-testproject',
        builder='local-manifest-presubmit-testprogram-testproject',
        git_repo='https://chrome-internal.googlesource.com/project1',
    )

  def checked_out_projects(api):
    """Returns StepData for the command used to find checked out projects.

    Note that the project name lines up with the project specified by
    project_config_cq_build.
    """
    return api.step_data(
        'cherry-pick gerrit changes.repo forall',
        stdout=api.raw_io.output('project1|src/project1|cros|master'))

  yield api.test(
      'basic',
      api.properties(LocalManifestPresubmitProperties(
          project='chromeos',
          manifest_groups=['partner-config'],
      )),
      project_config_cq_build(api),
      checked_out_projects(api),
      # The change should be applied.
      api.post_process(
          post_process.StepCommandContains,
          'cherry-pick gerrit changes.apply gerrit patch sets.git fetch',
          [
              'git',
              'fetch',
              'https://chrome-internal.googlesource.com/chromium/src',
              'refs/changes/56/123456/7:',
          ],
      ),
  )

  yield api.test(
      'no_project',
      api.properties(LocalManifestPresubmitProperties(
          manifest_groups=['partner-config'],
      )),
      project_config_cq_build(api),
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE,
                       '.*project must be specified.*'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no_manifest_groups',
      api.properties(LocalManifestPresubmitProperties(
          project='chromeos',
      )),
      project_config_cq_build(api),
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE,
                       '.*manifest group must be specified.*'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no_gerrit_changes',
      api.properties(LocalManifestPresubmitProperties(
          project='chromeos',
          manifest_groups=['partner-config'],
      )),
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE,
                       '.*At least one gerrit_change.*'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with_local_manifest',
      api.properties(LocalManifestPresubmitProperties(
          project='chromeos',
          manifest_groups=['partner-config'],
          local_manifest=LocalManifest(
              repo_url=('https://chrome-internal.googlesource.com'
                        '/chromeos/project/testproject1'),
              manifest_path='local_manifest.xml',
          ))),
      project_config_cq_build(api),
      checked_out_projects(api),
      # The change should be applied.
      api.post_process(
          post_process.StepCommandContains,
          'cherry-pick gerrit changes.apply gerrit patch sets.git fetch',
          [
              'git',
              'fetch',
              'https://chrome-internal.googlesource.com/chromium/src',
              'refs/changes/56/123456/7:',
          ],
      ),
  )
