# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/context',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_source',
    'src_state',
]

from recipe_engine import post_process

from PB.recipe_modules.chromeos.cros_source.examples.checkout_branch import (
    CheckoutBranchProperties)

PROPERTIES = CheckoutBranchProperties


def RunSteps(api, properties):

  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.ensure_synced_cache()
      api.assertions.assertEqual(api.cros_source.manifest_branch, '')
      api.assertions.assertEqual(api.cros_source.manifest_push, 'main')
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
      'basic', api.properties(CheckoutBranchProperties(branch_name=branch)),
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
      api.properties(CheckoutBranchProperties(branch_name=staging)),
      api.step_data(
          'checkout branch %s.ensure manifest is pinned.repo forall' % staging,
          stdout=api.raw_io.output('')),
      api.post_check(post_process.StatusSuccess),
      api.post_check(
          post_process.DoesNotRun,
          'checkout branch %s.ensure manifest is pinned.repo manifest' %
          staging),
      api.post_check(post_process.MustRun, 'checkout branch %s' % staging))
