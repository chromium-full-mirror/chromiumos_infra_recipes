# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Runs the presubmit for a project with checkout per local manifest."""

import contextlib

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from PB.project_mgmt.project import LocalManifest
from PB.recipes.chromeos.local_manifest_presubmit import (
    LocalManifestPresubmitProperties)

PROPERTIES = LocalManifestPresubmitProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'cros_infra_config',
    'git',
    'gs_step_logging',
    'repo',
    'src_state',
    'workspace_util',
]

# TODO(dburger): Rename this recipe. Initially it centered around syncing to a
# local manifest, but that is optional now.


def RunSteps(api, properties):
  # Because we use workspace_util to handle the source checkout, we need to call
  # configure_builder even though we don't have a builder config.
  commit = api.src_state.gitiles_commit
  if not commit.project:
    commit = (api.src_state.external_manifest
              if properties.use_external_manifest else
              api.src_state.internal_manifest).as_gitiles_commit_proto
  api.cros_infra_config.configure_builder(commit, api.src_state.gerrit_changes)

  if not properties.project:
    raise ValueError('The project must be specified.')

  if not properties.manifest_groups:
    raise ValueError('At least one manifest group must be specified.')

  if not api.buildbucket.build.input.gerrit_changes:
    raise ValueError('At least one gerrit_change must be specified.')

  local_manifests = []
  for lm in properties.local_manifests:
    local_manifests.append(
        api.repo.LocalManifest(repo=lm.repo_url, path=lm.manifest_path))

  if local_manifests and properties.manifest_branch:
    raise ValueError(
        'local_manifests cannot be specified if manifest_branch is specified')

  with api.context(infra_steps=True), \
      api.workspace_util.sync_to_manifest_groups(
          manifest_groups=properties.manifest_groups,
          manifest_branch=properties.manifest_branch,
          local_manifests=local_manifests,
          cache_path_override=api.src_state.workspace_path):
    api.workspace_util.apply_changes(api.buildbucket.build.input.gerrit_changes,
                                     fail_not_applicable=True)

    project = api.repo.project_info(properties.project)
    workspace_path = api.src_state.workspace_path
    project_path = workspace_path.join(project.path)

    with api.step.nest('prepare and execute presubmit'), \
        api.context(cwd=project_path):
      # Several checks require that we have an upstream tracking branch.
      # This requires us to have a branch, which we don't yet have.
      # Create the "__presubmit" branch, run the check, and then delete
      # it.
      # A refspec can't be used to set upstream, so extract the branch.
      # All of the projects will have a branch defined by the manifest.
      branch = api.git.extract_branch(project.branch, None)
      api.step('setup', ['git', 'checkout', '-b', '__presubmit'])
      api.step('set tracking', [
          'git', 'branch', '--set-upstream-to',
          '%s/%s' % (project.remote, branch)
      ])

      # infra_steps set in context take precedence over infra_step passed
      # to a step, so we make a new context here.
      with api.context(infra_steps=False), api.depot_tools.on_path(), \
          api.gs_step_logging.log_step_to_gs(properties.logging_gs_prefix):
        cmd = [
            'presubmit_support.py',
            '--json_output',
            api.json.output(),
            '--commit',
            '--verbose',
            '--recursive',
        ]
        if properties.presubmit_all_files:
          cmd.append('--all_files')
        api.step('presubmit_support', cmd,
                 stdout=api.raw_io.output(add_output_log=True))


def GenTests(api):

  def project_config_cq_build(api, extra_changes=None):
    """Returns a sample buildbucket project config cq build"""
    message = api.buildbucket.try_build_message(
        project='chromeos',
        bucket='testprogram-testproject',
        builder='local-manifest-presubmit-testprogram-testproject',
        git_repo='https://chrome-internal.googlesource.com/project1',
    )
    message.input.gerrit_changes.extend(extra_changes or [])
    return api.buildbucket.build(message)

  def checked_out_projects(api):
    """Returns StepData for the command used to find checked out projects.

    Note that the project name lines up with the project specified by
    project_config_cq_build.
    """
    return api.repo.project_infos_step_data(
        'cherry-pick gerrit changes.apply gerrit patch sets',
        [dict(project='project1')])

  def presubmit_with_output():
    """Returns StepData for a presubmit step with stdout."""
    return api.step_data('prepare and execute presubmit.presubmit_support',
                         stdout=api.raw_io.output('Test stdout from presubmit'))

  yield api.test(
      'basic',
      api.properties(
          LocalManifestPresubmitProperties(
              project='chromeos',
              manifest_groups=['partner-config'],
              local_manifests=[
                  LocalManifest(
                      repo_url=('https://chrome-internal.googlesource.com'
                                '/chromeos/project/testproject1'),
                      manifest_path='local_manifest.xml',
                  ),
                  LocalManifest(
                      repo_url=('https://chrome-internal.googlesource.com'
                                '/chromeos/program/testprogram1'),
                      manifest_path='local_manifest.xml',
                  ),
              ],
              logging_gs_prefix='testprogram-testproject/cq_logs',
              presubmit_all_files=True,
          )),
      project_config_cq_build(api),
      checked_out_projects(api),
      presubmit_with_output(),
      # The change should be applied.
      api.post_process(
          post_process.StepCommandContains,
          'cherry-pick gerrit changes.apply gerrit patch sets.git fetch',
          [
              'git',
              'fetch',
              'https://chrome-internal.googlesource.com/project1',
              'refs/changes/56/123456/7:',
          ],
      ),
  )

  yield api.test(
      'no_local_manifest',
      api.properties(
          LocalManifestPresubmitProperties(
              project='chromeos',
              manifest_groups=['partner-config'],
              logging_gs_prefix='testprogram-testproject/cq_logs',
              presubmit_all_files=True,
          )),
      project_config_cq_build(api),
      checked_out_projects(api),
      presubmit_with_output(),
      # The change should be applied.
      api.post_process(
          post_process.StepCommandContains,
          'cherry-pick gerrit changes.apply gerrit patch sets.git fetch',
          [
              'git',
              'fetch',
              'https://chrome-internal.googlesource.com/project1',
              'refs/changes/56/123456/7:',
          ],
      ),
  )

  yield api.test(
      'manifest_branch',
      api.properties(
          LocalManifestPresubmitProperties(
              project='chromeos',
              manifest_groups=['partner-config'],
              manifest_branch='release-R123',
          ),
      ),
      project_config_cq_build(api),
      api.post_process(
          post_process.StepCommandContains, 'ensure synced checkout.repo init',
          ['--manifest-branch', 'release-R123', '--groups', 'partner-config']),
      # If manifest_branch is passed, an internal checkout should be used and no
      # local manifest should be used.
      api.post_process(post_process.DoesNotRunRE,
                       '.*fetch.*:local_manifest.xml'),
  )

  yield api.test(
      'local_manifest_and_manifest_branch_specified',
      api.properties(
          LocalManifestPresubmitProperties(
              project='chromeos',
              manifest_groups=['partner-config'],
              local_manifests=[
                  LocalManifest(
                      repo_url=('https://chrome-internal.googlesource.com'
                                '/chromeos/project/testproject1'),
                      manifest_path='local_manifest.xml',
                  )
              ],
              manifest_branch='release-R123',
          ),
      ),
      project_config_cq_build(api),
      api.expect_exception('ValueError'),
      api.post_process(
          post_process.ResultReasonRE,
          ('.*local_manifests cannot be specified if manifest_branch is specified.*'
          ),
      ),
      api.post_process(post_process.DropExpectation),
  )

  extra_change = common_pb2.GerritChange(
      host='chrome-internal.googlesource.com', project='project1', change=101)

  # Checks against making sure a bot_update initialization is not being
  # used. bot_update blows up if it sees more than one change.
  yield api.test(
      'multiple_changes',
      api.properties(
          LocalManifestPresubmitProperties(
              project='chromeos',
              manifest_groups=['partner-config'],
              local_manifests=[
                  LocalManifest(
                      repo_url=('https://chrome-internal.googlesource.com'
                                '/chromeos/project/testproject1'),
                      manifest_path='local_manifest.xml',
                  )
              ],
          )),
      project_config_cq_build(api, extra_changes=[extra_change]),
      checked_out_projects(api),
      # The change should be applied.
      api.post_process(
          post_process.StepCommandContains,
          'cherry-pick gerrit changes.apply gerrit patch sets.git fetch',
          [
              'git',
              'fetch',
              'https://chrome-internal.googlesource.com/project1',
              'refs/changes/56/123456/7:',
          ],
      ),
      api.post_process(
          post_process.StepCommandContains,
          'cherry-pick gerrit changes.apply gerrit patch sets.git fetch (2)',
          [
              'git',
              'fetch',
              'https://chrome-internal.googlesource.com/project1',
              'refs/changes/01/101/0:',
          ],
      ),
  )

  yield api.test(
      'no_project',
      api.properties(
          LocalManifestPresubmitProperties(
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
      api.properties(
          LocalManifestPresubmitProperties(
              project='chromeos',
              manifest_groups=['partner-config'],
          )),
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE,
                       '.*At least one gerrit_change.*'),
      api.post_process(post_process.DropExpectation),
  )
