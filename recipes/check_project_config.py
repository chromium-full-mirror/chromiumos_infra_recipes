# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Checks a project conforms to its program's constraints."""

import contextlib

from recipe_engine import post_process

from PB.recipes.chromeos.check_project_config import (
    CheckProjectConfigProperties, ConfigBundleCheckoutPath)

PROPERTIES = CheckProjectConfigProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/path',
    'recipe_engine/python',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_source',
    'gerrit',
    'iterutils',
    'repo',
]


@contextlib.contextmanager
def checkout_manifest_groups(api, properties):
  """Returns a context with manifest groups checked out to cwd.

  Also applies gerrit_changes.

  Note that this function reuses most of the standard cros_source checkout code,
  but without any caching / overlayfs. The number of repos to checkout is
  usually much smaller than a full checkout, in which case the time to delete
  unused repos (which are present because of caching) is much larger than the
  time to sync the used repos. In addition, not caching reduces chances of
  leaking between runs of the recipe.
  """
  api.cros_source.ensure_synced_cache(
      init_opts={'groups': properties.manifest_groups},
      cache_path_override=api.cros_source.workspace_path)
  with api.context(cwd=api.cros_source.workspace_path):
    with api.step.nest('apply patch sets'):
      patch_sets = api.gerrit.fetch_patch_sets(
          api.buildbucket.build.input.gerrit_changes)

      # It is possible that input.gerrit_changes includes changes to repos this
      # builder is not allowed to read (e.g. if Cq-Depends groups together
      # changes that affect multiple project repos). In this case,
      # apply_gerrit_patch_sets will fail. Catch the failure and report it as a
      # StepFailure (i.e. not an InfraFailure), with a message that may help the
      # submitter.
      #
      # For now just catch all failures of apply_gerrit_patch_sets. If needed,
      # we can add more filters (e.g. on stdout, exact step that failed) for the
      # above case.
      try:
        api.cros_source.apply_gerrit_patch_sets(patch_sets)
      except api.step.StepFailure:
        raise api.step.StepFailure(
            ("Failed to apply patch sets. This may be "
             "the result of Cq-Depends that include CLs outside of this "
             "builder's read ACLs."))
    yield


def RunSteps(api, properties):
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

  # Do work in a context with manifest groups checked out. Most steps are infra
  # steps, so make this the default. Non-infra steps specify this explicitly.
  with api.context(infra_steps=True), checkout_manifest_groups(api, properties):
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
      raise api.step.InfraFailure(
          'generate.sh not found. Expected at %s' % generate_path)

    if not api.path.exists(checker_path):  #pragma: nocover
      raise api.step.InfraFailure(
          'Checker not found. Expected at %s' % checker_path)

    api.step('generate proto bindings', [generate_path])

    program_path = api.context.cwd.join(
        properties.program_config_bundle_checkout_path.repo_checkout_path,
        properties.program_config_bundle_checkout_path.config_path)

    project_path = api.context.cwd.join(
        properties.project_config_bundle_checkout_path.repo_checkout_path,
        properties.project_config_bundle_checkout_path.config_path)

    # Call checker with checked out program and project. Note that a failure
    # here is not considered an infra failure. infra_steps set in context takes
    # precedent over infra_step passed to api.step, so need to create a new
    # context here.
    with api.context(infra_steps=False):
      checker_args = ['--program', program_path, '--project', project_path]
      api.python('check constraints', checker_path, checker_args)


def GenTests(api):

  def properties(api):
    """Returns a basic set of valid properties."""
    return api.properties(
        manifest_groups=['partner-config', 'testprogram-testproject'],
        chromiumos_config_checkout_path='src/config',
        program_config_bundle_checkout_path=ConfigBundleCheckoutPath(
            repo_checkout_path='src/program/testprogram',
            config_path='generated/config.binaryproto',
        ),
        project_config_bundle_checkout_path=ConfigBundleCheckoutPath(
            repo_checkout_path='src/project/testproject',
            config_path='generated/config.binaryproto',
        ),
    )

  def project_config_cq_build(api):
    """Returns a sample buildbucket project config cq build"""
    return api.buildbucket.try_build(
        project="chromeos", bucket="testprogram-testproject",
        builder="config-checker-testprogram-testproject")

  yield api.test(
      'basic',
      properties(api),
      project_config_cq_build(api),
      api.post_process(post_process.StepCommandContains,
                       'ensure synced checkout.repo init',
                       ['--groups', 'partner-config,testprogram-testproject']),
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
      properties(api),
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE,
                       '.*At least one gerrit_change must be specified.*'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'checker_failed',
      properties(api),
      project_config_cq_build(api),
      api.step_data('check constraints', retcode=1),
      api.post_process(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'cannot_access_gerrit_changes',
      properties(api),
      project_config_cq_build(api),
      api.step_data(
          'apply patch sets.apply gerrit patch sets.repo forall',
          retcode=1,
          stdout=api.raw_io.output('error: project othertestproject not found'),
      ),
      api.post_process(
          post_process.ResultReason,
          "Failed to apply patch sets. This may be the result of "
          "Cq-Depends that include CLs outside of this builder's read ACLs."),
      api.post_process(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
  )
