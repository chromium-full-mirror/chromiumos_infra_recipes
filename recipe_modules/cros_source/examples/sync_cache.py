# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'recipe_engine/properties',
    'cros_source',
    'src_state',
]

from recipe_engine import post_process

from PB.recipe_modules.chromeos.cros_source.examples.sync_cache import (
    SyncCacheProperties)

PROPERTIES = SyncCacheProperties


def RunSteps(api, properties):
  path = None
  if properties.cache_path_override:
    path = api.path['cache'].join(properties.cache_path_override)
  with api.cros_source.checkout_overlays_context():
    api.cros_source.ensure_synced_cache(manifest_url=properties.manifest_url,
                                        cache_path_override=path)

def GenTests(api):

  def verify_manifest_url(check, steps, expected, name=None):
    name = name or "ensure synced checkout.repo init"
    data = steps[name].cmd
    return check('--manifest-url' in data and
                 data[data.index('--manifest-url') + 1] == expected)

  external_url = api.src_state.external_manifest.url
  internal_url = api.src_state.internal_manifest.url

  yield api.cros_source.test(
      'basic',
      api.post_check(verify_manifest_url, internal_url,
                     'sync cached directory.ensure synced checkout.repo init'),
      api.post_check(post_process.StatusSuccess))

  yield api.cros_source.test(
      'internal',
      api.properties(
          SyncCacheProperties(
              manifest_url=api.src_state.internal_manifest.url)),
      api.post_check(verify_manifest_url, internal_url,
                     'sync cached directory.ensure synced checkout.repo init'),
      api.post_check(post_process.DoesNotRun, 'override manifest url'),
      api.post_check(post_process.StatusSuccess))

  yield api.cros_source.test(
      'custom',
      api.properties(
          SyncCacheProperties(manifest_url=api.src_state.external_manifest.url,
                              cache_path_override='chromiumos-external')),
      api.post_check(verify_manifest_url, external_url),
      api.post_check(post_process.StatusSuccess))
