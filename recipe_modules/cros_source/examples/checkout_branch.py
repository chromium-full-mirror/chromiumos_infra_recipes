# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

from PB.recipe_modules.chromeos.cros_source.examples.checkout_branch import CheckoutBranchProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/swarming',
    'cros_source',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = CheckoutBranchProperties


def RunSteps(api, properties):

  api.cros_source.configure_builder(default_main=False)
  with api.cros_source.checkout_overlays_context(snapshot_mount=True):
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.ensure_synced_cache(is_staging=properties.is_staging)
      branch_name = 'staging-snapshot' if properties.is_staging else 'snapshot'
      api.assertions.assertEqual(api.cros_source.manifest_branch, branch_name)
      # Manifest changes get pushed to main
      branch_name = branch_name if properties.is_staging else 'main'
      api.assertions.assertEqual(api.cros_source.manifest_push, branch_name)
      api.cros_source.checkout_branch(api.src_state.internal_manifest.url,
                                      properties.branch_name)
      api.assertions.assertEqual(api.cros_source.manifest_branch,
                                 properties.branch_name)
      api.assertions.assertEqual(api.cros_source.manifest_push,
                                 properties.branch_name)


def GenTests(api):

  # Checking out an unpinned branch.
  branch = 'release-R86-13421.B'
  yield api.cros_source.test(
      'basic', 'snapshot',
      api.properties(
          CheckoutBranchProperties(branch_name=branch, is_staging=False)),
      api.post_check(post_process.StatusSuccess),
      api.post_check(
          post_process.MustRun,
          'checkout branch %s.ensure manifest is pinned.repo manifest' %
          branch),
      api.post_check(post_process.MustRun, 'checkout branch %s' % branch))

  # Checking out a pinned branch.
  staging = 'staging-snapshot'
  yield api.cros_source.test(
      'staging-snapshot',
      staging,
      api.properties(
          CheckoutBranchProperties(branch_name=staging, is_staging=True)),
      api.step_data(
          'checkout branch %s.ensure manifest is pinned.repo forall' % staging,
          stdout=api.raw_io.output('')),
      api.post_check(post_process.StatusSuccess),
      api.post_check(
          post_process.DoesNotRun,
          'checkout branch %s.ensure manifest is pinned.repo manifest' %
          staging),
      api.post_check(post_process.MustRun, 'checkout branch %s' % staging),
  )
