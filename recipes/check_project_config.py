# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Checks a project conforms to its program's constraints."""

import contextlib

from recipe_engine import post_process

from PB.project_mgmt.project import LocalManifest
from PB.recipes.chromeos.check_project_config import (
    CheckProjectConfigProperties,
    ConfigBundleCheckoutPath,
)

PROPERTIES = CheckProjectConfigProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/path',
    'recipe_engine/python',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_infra_config',
    'gerrit',
    'gs_step_logging',
    'iterutils',
    'repo',
    'src_state',
    'workspace_util',
]


def RunSteps(api, properties):
  # Because we use workspace_util to handle the source checkout, we need to call
  # configure_builder even though we don't have a builder config.
  commit = api.src_state.gitiles_commit
  if not commit.project:
    commit = (api.src_state.external_manifest
              if properties.use_external_manifest else
              api.src_state.internal_manifest).as_gitiles_commit_proto
  api.cros_infra_config.configure_builder(commit, api.src_state.gerrit_changes)

  if not properties.manifest_groups:
    raise ValueError('At least one manifest group must be specified.')

  if not api.buildbucket.build.input.gerrit_changes:
    raise ValueError('At least one gerrit_change must be specified.')

  if not all((
      properties.chromiumos_config_checkout_path,
      properties.program_config_bundle_checkout_path.repo_checkout_path,
      properties.program_config_bundle_checkout_path.config_path,
      properties.project_config_bundle_checkout_path.repo_checkout_path,
      properties.project_config_bundle_checkout_path.config_path,
  )):
    raise ValueError('All checkout_paths and config_paths must be specified.')

  if not (properties.local_manifest.repo_url and
          properties.local_manifest.manifest_path):
    raise ValueError('local_manifest repo and path must be specified')

  local_manifest = api.repo.LocalManifest(
      repo=properties.local_manifest.repo_url,
      path=properties.local_manifest.manifest_path)

  # Do work in a context with manifest groups checked out. Most steps are infra
  # steps, so make this the default. Non-infra steps specify this explicitly.
  # Note the overriding of the cache path in the sync_to_manifest_groups call.
  # This is done because these checkouts are much smaller than a full checkout
  # and thus skipping the standard cache avoids a costly time sink of deleting
  # unused repos.
  with api.context(infra_steps=True), \
      api.workspace_util.sync_to_manifest_groups(
          properties.manifest_groups,
          local_manifest=local_manifest,
          cache_path_override=api.src_state.workspace_path):
    api.workspace_util.apply_changes(api.buildbucket.build.input.gerrit_changes,
                                     fail_not_applicable=True)

    chromiumos_config_path = properties.chromiumos_config_checkout_path

    generate_path = api.context.cwd.join(chromiumos_config_path, 'generate.sh')
    checker_path = api.context.cwd.join(chromiumos_config_path,
                                        'payload_utils/checker.py')

    # mock_add_paths marks that the path exists for tests. The exists call
    # doesn't actually perform a Recipes step, it just calls the standard
    # Python os.exists (and in testing it calls a fake implementation of
    # os.exists). Thus, this mocking can't be done in GenTests. This also means
    # there isn't a good way to create a test case that triggers the failure
    # case.
    api.path.mock_add_paths(generate_path)
    api.path.mock_add_paths(checker_path)

    if not api.path.exists(generate_path):  # pragma: nocover
      raise api.step.InfraFailure('generate.sh not found. Expected at %s' %
                                  generate_path)

    if not api.path.exists(checker_path):  #pragma: nocover
      raise api.step.InfraFailure('Checker not found. Expected at %s' %
                                  checker_path)

    api.step('generate proto bindings', [generate_path])

    program_path = api.context.cwd.join(
        properties.program_config_bundle_checkout_path.repo_checkout_path,
        properties.program_config_bundle_checkout_path.config_path)

    project_path = api.context.cwd.join(
        properties.project_config_bundle_checkout_path.repo_checkout_path,
        properties.project_config_bundle_checkout_path.config_path)

    factory_dir = api.context.cwd.join(
        properties.project_config_bundle_checkout_path.repo_checkout_path,
        properties.factory_dir,
    )

    # Call checker with checked out program and project. Note that a failure
    # here is not considered an infra failure. infra_steps set in context takes
    # precedent over infra_step passed to api.step, so need to create a new
    # context here.
    with api.context(
        infra_steps=False,
    ), api.gs_step_logging.log_step_to_gs(
        properties.logging_gs_prefix,
    ):
      checker_args = [
          '--program', program_path, '--project', project_path, '--factory_dir',
          factory_dir
      ]
      api.python(
          'check constraints',
          checker_path,
          checker_args,
          stdout=api.raw_io.output(add_output_log=True),
      )


def GenTests(api):

  def properties_dict(extra_props={}):
    """Returns a dict of basic valid properties, updated with extra_props."""
    props = {
        'manifest_groups': ['partner-config'],
        'local_manifest':
            LocalManifest(
                repo_url=('https://chrome-internal.googlesource.com'
                          '/chromeos/project/testproject1'),
                manifest_path='local_manifest.xml',
            ),
        'chromiumos_config_checkout_path':
            'src/config',
        'program_config_bundle_checkout_path':
            ConfigBundleCheckoutPath(
                repo_checkout_path='src/program/testprogram',
                config_path='generated/config.binaryproto',
            ),
        'project_config_bundle_checkout_path':
            ConfigBundleCheckoutPath(
                repo_checkout_path='src/project/testproject',
                config_path='generated/config.binaryproto',
            ),
        'logging_gs_prefix':
            'testprogram-testproject/cq_logs',
        'factory_dir':
            'factory',
    }
    props.update(extra_props)
    return props

  def project_config_cq_build(api):
    """Returns a sample buildbucket project config cq build"""
    return api.buildbucket.try_build(
        project='chromeos',
        bucket='testprogram-testproject',
        builder='config-checker-testprogram-testproject',
        git_repo='https://chrome-internal.googlesource.com/project1',
    )

  def checked_out_projects(api):
    """Returns StepData for the command used to find checked out projects.

    Note that the project name lines up with the project specified by
    project_config_cq_build.
    """
    return api.step_data(
        'cherry-pick gerrit changes.repo forall', stdout=api.raw_io.output(
            'project1|src/project1|cros|refs/heads/master|refs/heads/branch'))

  def check_constraints_with_output():
    """Returns StepData for a check constraints step with stdout."""
    return api.step_data(
        'check constraints',
        stdout=api.raw_io.output('Test stdout from constraint checker'))

  yield api.test(
      'basic',
      api.properties(**properties_dict()),
      project_config_cq_build(api),
      # The input GerritChange is in a checked out project.
      checked_out_projects(api),
      check_constraints_with_output(),
      api.post_process(post_process.StepCommandContains,
                       'ensure synced checkout.repo init',
                       ['--groups', 'partner-config']),
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
      'local_manifest_missing',
      api.properties(**properties_dict(
          extra_props={
              'local_manifest': LocalManifest(
                  repo_url='',
                  manifest_path='',
              ),
          })),
      project_config_cq_build(api),
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE,
                       ('.*local_manifest repo and path must be specified.*')),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'checkout_paths_missing',
      api.properties(
          manifest_groups=['partner-config', 'testprogram-testproject'],
          chromiumos_config_checkout_path='src/config',
      ),
      project_config_cq_build(api),
      api.expect_exception('ValueError'),
      api.post_process(
          post_process.ResultReasonRE,
          ('.*All checkout_paths and config_paths must be specified.*')),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no_manifest_groups',
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE,
                       '.*At least one manifest group must be specified.*'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no_gerrit_changes',
      api.properties(**properties_dict()),
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE,
                       '.*At least one gerrit_change must be specified.*'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'checker_failed',
      api.properties(**properties_dict()),
      project_config_cq_build(api),
      api.step_data('check constraints', retcode=1),
      api.post_process(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'cannot_access_gerrit_changes',
      api.properties(**properties_dict()),
      project_config_cq_build(api),
      # The input GerritChange is not in a checked out project. The discarded
      # changes are logged and the build succeeds.
      api.post_process(
          post_process.StepTextEquals,
          'cherry-pick gerrit changes',
          'Discarded changes: 123456',
      ),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
