# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_source',
    'repo',
    'src_state',
]

from recipe_engine import post_process

from PB.recipe_modules.chromeos.cros_source.examples.checkout_manifests import (
    CheckoutManifestsProperties)

PROPERTIES = CheckoutManifestsProperties


def RunSteps(api, properties):

  snapshot_xml = api.src_state.internal_manifest.path.join('snapshot.xml')
  # Before we checkout manifests, the branch_manifest_file shall be
  # snapshot.xml.
  api.assertions.assertEqual(api.cros_source.branch_manifest_file, snapshot_xml)

  with api.cros_source.checkout_overlays_context():
    api.cros_source.checkout_manifests(
        checkout_external=properties.checkout_external)
    api.assertions.assertEqual(api.cros_source.manifest_branch,
                               properties.branch_name)

  if api.path.exists(snapshot_xml):
    api.assertions.assertEqual(snapshot_xml,
                               api.cros_source.branch_manifest_file)
  else:
    api.assertions.assertNotEqual(snapshot_xml,
                                  api.cros_source.branch_manifest_file)


def GenTests(api):

  # The normal case for postsubmit: checkout the external manifest, so we can
  # push manifest refs.
  yield api.cros_source.test(
      'basic-success', api.post_check(post_process.StatusSuccess),
      api.properties(CheckoutManifestsProperties(checkout_external=True)),
      revision=None, cq=False, git_ref=None)

  yield api.cros_source.test(
      'basic-failure',
      api.properties(CheckoutManifestsProperties(checkout_external=True)),
      api.repo.fail_repo_sync(True),
      api.post_check(post_process.StepFailure, 'retry cache sync'),
      revision=None, cq=False, git_ref=None)

  # Running on an unpinned branch.
  branch = 'release-R88-13597.B'
  yield api.cros_source.test(
      'branch', api.properties(CheckoutManifestsProperties(branch_name=branch)),
      api.cros_source.snapshot_xml_exists(False),
      api.post_check(post_process.StatusSuccess),
      git_ref='refs/heads/{}'.format(branch), cq=False)

  # Two footers
  yield api.cros_source.test(
      'two-footers',
      api.properties(CheckoutManifestsProperties(branch_name='snapshot')),
      api.post_check(post_process.StatusAnyFailure),
      api.step_data('read git footers',
                    stdout=api.raw_io.output('\n'.join(['1' * 40, '2' * 40]))),
      cq=False)
