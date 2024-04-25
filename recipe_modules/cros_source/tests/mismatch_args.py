# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cros_source.tests.mismatch_args import MismatchArgsProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'cros_source',
    'src_state',
]


PROPERTIES = MismatchArgsProperties


def RunSteps(api, properties):
  api.cros_source.configure_builder(default_main=True)
  with api.cros_source.checkout_overlays_context(), \
      api.assertions.assertRaises(ValueError):
    api.cros_source.ensure_synced_cache(
        manifest_url=properties.manifest_url,
        cache_path_override=api.path.cache_dir.joinpath(
            properties.cache_path_override)
        if properties.cache_path_override else None)


def GenTests(api):
  yield api.cros_source.test(
      'basic', 'snapshot',
      api.properties(
          MismatchArgsProperties(
              manifest_url=api.src_state.external_manifest.url)))
