# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cros_source.examples.sync_cache import SyncCacheProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/swarming',
    'cros_source',
    'gcloud',
    'src_state',
]

PROPERTIES = SyncCacheProperties



def RunSteps(api, properties):
  _ = api.cros_source.use_external_source_cache
  api.cros_source.configure_builder(default_main=True)
  path = None
  if properties.cache_path_override:
    path = api.path['cache'].join(properties.cache_path_override)
  manifest_branch = 'release-R90-13816.B'
  with api.cros_source.checkout_overlays_context():
    api.cros_source.ensure_synced_cache(
        manifest_url=properties.manifest_url, cache_path_override=path,
        manifest_branch_override=manifest_branch)


def GenTests(api):

  def verify_manifest_url(check, steps, expected, name=None):
    name = name or 'ensure synced checkout.repo init'
    data = steps[name].cmd
    return check('--manifest-url' in data and
                 data[data.index('--manifest-url') + 1] == expected)

  external_url = api.src_state.external_manifest.url
  internal_url = api.src_state.internal_manifest.url
  manifest_branch = 'snapshot'

  yield api.cros_source.test(
      'basic',
      manifest_branch,
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-lmno'),
      api.post_check(verify_manifest_url, internal_url,
                     'sync cached directory.ensure synced checkout.repo init'),
  )

  yield api.cros_source.test(
      'internal',
      manifest_branch,
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-lmno'),
      api.properties(
          SyncCacheProperties(
              manifest_url=api.src_state.internal_manifest.url)),
      api.post_check(verify_manifest_url, internal_url,
                     'sync cached directory.ensure synced checkout.repo init'),
      api.post_check(post_process.DoesNotRun, 'override manifest url'),
  )

  yield api.cros_source.test(
      'custom',
      manifest_branch,
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-lmno'),
      api.properties(
          SyncCacheProperties(manifest_url=api.src_state.external_manifest.url,
                              cache_path_override='chromiumos')),
      api.properties(
          **{'$chromeos/cros_source': {
              'use_external_source_cache': True,
          }}),
      api.post_check(verify_manifest_url, external_url),
  )
