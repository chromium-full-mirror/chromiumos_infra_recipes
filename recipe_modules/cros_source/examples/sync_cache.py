# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/swarming',
    'cros_source',
    'gcloud',
    'src_state',
]

from recipe_engine import post_process

from PB.recipe_modules.chromeos.cros_source.examples.sync_cache import (
    SyncCacheProperties)

PROPERTIES = SyncCacheProperties

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api, properties):
  api.cros_source.configure_builder(default_main=True)
  path = None
  if properties.cache_path_override:
    path = api.path['cache'].join(properties.cache_path_override)
  manifest_branch = 'release-R90-13816.B'
  with api.cros_source.checkout_overlays_context(snapshot_mount=True):
    api.cros_source.ensure_synced_cache(
        manifest_url=properties.manifest_url, cache_path_override=path,
        manifest_branch_override=manifest_branch)


def GenTests(api):

  def verify_manifest_url(check, steps, expected, name=None):
    name = name or "ensure synced checkout.repo init"
    data = steps[name].cmd
    return check('--manifest-url' in data and
                 data[data.index('--manifest-url') + 1] == expected)

  external_url = api.src_state.external_manifest.url
  internal_url = api.src_state.internal_manifest.url
  manifest_branch = 'snapshot'

  yield api.cros_source.test(
      'basic', manifest_branch,
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-lmno'),
      api.post_check(verify_manifest_url, internal_url,
                     'sync cached directory.ensure synced checkout.repo init'),
      api.post_check(post_process.StatusSuccess))

  yield api.cros_source.test(
      'internal', manifest_branch,
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-lmno'),
      api.properties(
          SyncCacheProperties(
              manifest_url=api.src_state.internal_manifest.url)),
      api.post_check(verify_manifest_url, internal_url,
                     'sync cached directory.ensure synced checkout.repo init'),
      api.post_check(post_process.DoesNotRun, 'override manifest url'),
      api.post_check(post_process.StatusSuccess))

  yield api.cros_source.test(
      'custom', manifest_branch,
      api.gcloud.infra_host('chromeos-ci-infra-us-central1-b-x16-0-lmno'),
      api.properties(
          SyncCacheProperties(manifest_url=api.src_state.external_manifest.url,
                              cache_path_override='chromiumos-external')),
      api.post_check(verify_manifest_url, external_url),
      api.post_check(post_process.StatusSuccess))
