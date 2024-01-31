# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cros_source.examples.checkout_manifests import CheckoutManifestsProperties

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


PROPERTIES = CheckoutManifestsProperties


def RunSteps(api, properties):

  api.cros_source.configure_builder(default_main=True)
  snapshot_xml = api.src_state.internal_manifest.path.join('snapshot.xml')
  # Before we checkout manifests, the branch_manifest_file shall be
  # snapshot.xml.
  api.assertions.assertEqual(api.cros_source.branch_manifest_file, snapshot_xml)

  with api.cros_source.checkout_overlays_context():
    api.cros_source.checkout_manifests(
        checkout_external=properties.checkout_external,
        checkout_internal=not properties.only_external)
    if properties.only_external and not properties.checkout_external:
      return
    api.assertions.assertEqual(api.cros_source.manifest_branch,
                               properties.branch_name or 'main')

    is_tot = api.cros_source.manifest_branch in [
        'main', 'snapshot', 'staging-snapshot'
    ]
    api.assertions.assertEqual(api.cros_source.is_tot, is_tot)

  if api.path.exists(snapshot_xml):
    api.assertions.assertEqual(snapshot_xml,
                               api.cros_source.branch_manifest_file)
  else:
    api.assertions.assertNotEqual(snapshot_xml,
                                  api.cros_source.branch_manifest_file)
  api.cros_source.test_api.manifest_branch = 'some-other-branch'
  api.assertions.assertEqual('some-other-branch',
                             api.cros_source.manifest_branch)


def GenTests(api):
  manifest_branch = 'snapshot'
  # The normal case for postsubmit: checkout the external manifest, so we can
  # push manifest refs.
  yield api.cros_source.test(
      'basic-success', manifest_branch,
      api.properties(CheckoutManifestsProperties(checkout_external=True)),
      revision=None, cq=False, git_ref=None)

  yield api.cros_source.test(
      'basic-failure',
      manifest_branch,
      api.properties(CheckoutManifestsProperties(checkout_external=True)),
      api.repo.fail_repo_sync(True),
      revision=None,
      cq=False,
      git_ref=None,
      status='INFRA_FAILURE',
  )

  # Running on an unpinned branch.
  release_branch = 'release-R88-13597.B'
  yield api.cros_source.test(
      'branch', release_branch,
      api.properties(CheckoutManifestsProperties(branch_name=release_branch)),
      api.cros_source.snapshot_xml_exists(False),
      git_ref='refs/heads/{}'.format(release_branch), cq=False)

  # Two footers
  yield api.cros_source.test(
      'two-footers',
      manifest_branch,
      api.properties(CheckoutManifestsProperties(branch_name=manifest_branch)),
      api.step_data('read git footers',
                    stdout=api.raw_io.output('\n'.join(['1' * 40, '2' * 40]))),
      cq=False,
      status='FAILURE',
  )

  yield api.cros_source.test(
      'only-external', manifest_branch,
      api.properties(
          CheckoutManifestsProperties(only_external=True,
                                      checkout_external=True)), revision=None,
      cq=False, git_ref=None)

  yield api.cros_source.test(
      'noop', manifest_branch,
      api.properties(
          CheckoutManifestsProperties(only_external=True,
                                      checkout_external=False)), revision=None,
      cq=False, git_ref=None)
