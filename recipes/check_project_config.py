# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Checks a project conforms to its program's constraints."""

import contextlib

from recipe_engine import post_process

from PB.recipes.chromeos.check_project_config import (
    CheckProjectConfigProperties)

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
      api.cros_source.apply_gerrit_patch_sets(patch_sets)
    yield


def RunSteps(api, properties):
  if not properties.manifest_groups:
    raise ValueError('At least one manifest group must be specified.')

  if not api.buildbucket.build.input.gerrit_changes:
    raise ValueError('At least one gerrit_change must be specified.')

  # Do work in a context with manifest groups checked out. Most steps are infra
  # steps, so make this the default. Non-infra steps specify this explicitly.
  with api.context(infra_steps=True), checkout_manifest_groups(api, properties):
    with api.step.nest('gather project info'):
      project_infos = api.repo.project_infos()

    chromiumos_config_info = api.iterutils.get_one(
        project_infos, lambda info: info.name == 'chromiumos/config',
        "Expected exactly one 'chromiumos/config' repo.")

    program_info = api.iterutils.get_one(
        project_infos, lambda info: info.name.startswith('chromeos/program'),
        "Expected exactly one program repo.")

    project_info = api.iterutils.get_one(
        project_infos, lambda info: info.name.startswith('chromeos/project'),
        "Expected exactly one project repo.")

    generate_path = api.context.cwd.join(chromiumos_config_info.path,
                                         'generate.sh')
    checker_path = api.context.cwd.join(chromiumos_config_info.path,
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

    # Call checker with checked out program and project. Note that a failure
    # here is not considered an infra failure. infra_steps set in context takes
    # precedent over infra_step passed to api.step, so need to create a new
    # context here.
    with api.context(infra_steps=False):
      checker_args = [
          '--program', program_info.path, '--project', project_info.path
      ]
      api.python('check constraints', checker_path, checker_args)


def GenTests(api):

  def properties(api):
    """Returns a basic set of valid properties."""
    return api.properties(
        manifest_groups=['partner-config', 'testprogram-testproject'])

  def project_config_cq_build(api):
    """Returns a sample buildbucket project config cq build"""
    return api.buildbucket.try_build(
        project="chromeos", bucket="testprogram-testproject",
        builder="config-checker-testprogram-testproject")

  def project_info_step_data(api):
    """Returns step data with project info for chromiumos/config, a test project
       repo, and a test program repo.
    """
    return api.override_step_data(
        'gather project info.repo forall',
        api.raw_io.stream_output('\n'.join(
            '%s|%s|cros|refs/heads/master' % (name, path) for name, path in [
                ('chromiumos/config', 'src/config'),
                ('chromeos/program/testprogram', 'src/program/testprogram'),
                ('chromeos/project/testproject', 'src/project/testproject'),
            ])),
    )

  yield api.test(
      'basic',
      properties(api),
      project_config_cq_build(api),
      project_info_step_data(api),
      api.post_process(post_process.StepCommandContains,
                       'ensure synced checkout.repo init',
                       ['--groups', 'partner-config,testprogram-testproject']),
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
      'repo_missing',
      properties(api),
      project_config_cq_build(api),
      api.expect_exception('ValueError'),
      api.post_process(post_process.ResultReasonRE,
                       ".*Expected exactly one 'chromiumos/config' repo.*"),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'checker_failed',
      properties(api),
      project_config_cq_build(api),
      project_info_step_data(api),
      api.step_data('check constraints', retcode=1),
      api.post_process(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
  )
