# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Checks a project conforms to its program's constraints."""

from recipe_engine import post_process

from PB.recipes.chromeos.check_project_config import (
    CheckProjectConfigProperties)

PROPERTIES = CheckProjectConfigProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_source',
    'iterutils',
    'repo',
]


def RunSteps(api, properties):
  if not properties.manifest_groups:
    raise ValueError('At least one manifest group must be specified.')

  # Using overlayfs and repo caching mechanisms is probably unnecessary, because
  # the checkout is expected to be small. Use it anyway, for the small benefit
  # offered, and for consistency with other code.
  with api.cros_source.checkout_overlays_context(), \
       api.context(cwd=api.cros_source.workspace_path):
    api.cros_source.ensure_synced_cache(
        init_opts={'groups': properties.manifest_groups})
    api.cros_source.sync_snapshot(api.buildbucket.gitiles_commit)

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


def GenTests(api):

  def properties(api):
    """Returns a basic set of valid properties."""
    return api.properties(
        manifest_groups=['partner-config', 'testprogram-testproject'])

  def project_info_step_data(api):
    """Returns step data with project info for chromiumos/config, a test project
       repo, and a test program repo.
    """
    return api.override_step_data(
        'repo forall',
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
      project_info_step_data(api),
      api.post_process(
          post_process.StepCommandContains, 'ensure synced checkout.repo init',
          ['--groups', 'partner-config,testprogram-testproject']
      )
  )

  yield api.test(
      'no_manifest_groups',
      api.expect_exception('ValueError'),
      api.post_process(
          post_process.ResultReasonRE,
          '.*At least one manifest group must be specified.*'
      ),
      api.post_process(post_process.DropExpectation)
  )

  yield api.test(
      'repo_missing',
      properties(api),
      api.expect_exception('ValueError'),
      api.post_process(
          post_process.ResultReasonRE,
          ".*Expected exactly one 'chromiumos/config' repo.*"
      ),
      api.post_process(post_process.DropExpectation)
  )
