# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cros_source.examples.checkout_branch import CheckoutBranchProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/swarming',
    'cros_source',
    'src_state',
]


PROPERTIES = CheckoutBranchProperties


def RunSteps(api, properties):

  api.cros_source.configure_builder(default_main=False)
  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.ensure_synced_cache(is_staging=properties.is_staging)
      branch_name = 'staging-snapshot' if properties.is_staging else 'snapshot'
      api.assertions.assertEqual(api.cros_source.manifest_branch, branch_name)
      # Manifest changes get pushed to main
      api.assertions.assertEqual(api.cros_source.manifest_push, 'main')

      # Now try checking out the branch.
      api.cros_source.checkout_branch(api.src_state.internal_manifest.url,
                                      properties.branch_name)
      api.assertions.assertEqual(api.cros_source.manifest_branch,
                                 properties.branch_name)
      branch_name = 'main' if properties.branch_name in (
          'snapshot', 'staging-snapshot') else properties.branch_name
      api.assertions.assertEqual(api.cros_source.manifest_push, branch_name)


def GenTests(api):

  # Source cache syncs to 'snapshot', we ask for 'release-R86-13421.B'.
  branch = 'release-R86-13421.B'
  yield api.cros_source.test(
      'basic', 'snapshot',
      api.properties(
          CheckoutBranchProperties(branch_name=branch, is_staging=False)),
      api.post_check(
          post_process.MustRun,
          'checkout branch %s.ensure manifest is pinned.repo manifest' %
          branch),
      api.post_check(post_process.MustRun, 'checkout branch %s' % branch))

  # Source cache syncs to 'snapshot', we ask for 'main'.
  branch = 'main'
  yield api.cros_source.test(
      'snapshot-main',
      'snapshot',
      api.properties(
          CheckoutBranchProperties(branch_name=branch, is_staging=False)),
      api.step_data(
          'checkout branch %s.ensure manifest is pinned.repo forall' % branch,
          stdout=api.raw_io.output('')),
      api.post_check(
          post_process.DoesNotRun,
          'checkout branch %s.ensure manifest is pinned.repo manifest' %
          branch),
      api.post_check(post_process.MustRun, 'checkout branch %s' % branch),
  )

  # Source cache syncs to 'snapshot', we ask for 'snapshot'.
  # Test verifies that cros_source.manifest_push is still 'main'.
  branch = 'snapshot'
  yield api.cros_source.test(
      'snapshot',
      'snapshot',
      api.properties(
          CheckoutBranchProperties(branch_name=branch, is_staging=False)),
      api.step_data(
          'checkout branch %s.ensure manifest is pinned.repo forall' % branch,
          stdout=api.raw_io.output('')),
      api.post_check(
          post_process.DoesNotRun,
          'checkout branch %s.ensure manifest is pinned.repo manifest' %
          branch),
      api.post_check(post_process.MustRun, 'checkout branch %s' % branch),
  )

  # Source cache syncs to 'staging-snapshot', we ask for 'main'.
  branch = 'main'
  yield api.cros_source.test(
      'staging-snapshot-main',
      'staging-snapshot',
      api.properties(
          CheckoutBranchProperties(branch_name='main', is_staging=True)),
      api.step_data(
          'checkout branch %s.ensure manifest is pinned.repo forall' % branch,
          stdout=api.raw_io.output('')),
      api.post_check(
          post_process.DoesNotRun,
          'checkout branch %s.ensure manifest is pinned.repo manifest' %
          branch),
      api.post_check(post_process.MustRun, 'checkout branch %s' % branch),
  )

  # Source cache syncs to 'staging-snapshot', we ask for 'staging-snapshot'.
  # Test verifies that cros_source.manifest_push is still 'main'.
  branch = 'staging-snapshot'
  yield api.cros_source.test(
      'staging-snapshot',
      'staging-snapshot',
      api.properties(
          CheckoutBranchProperties(branch_name=branch, is_staging=True)),
      api.step_data(
          'checkout branch %s.ensure manifest is pinned.repo forall' % branch,
          stdout=api.raw_io.output('')),
      api.post_check(
          post_process.DoesNotRun,
          'checkout branch %s.ensure manifest is pinned.repo manifest' %
          branch),
      api.post_check(post_process.MustRun, 'checkout branch %s' % branch),
  )
