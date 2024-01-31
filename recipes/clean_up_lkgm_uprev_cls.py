# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that tests chromite.

This recipe lives on its own because it is agnostic of ChromeOS build targets.
"""

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/step',
    'recipe_engine/properties',
    'cros_lkgm',
    'cros_infra_config',
    'cros_source',
    'bot_scaling',
    'test_util',
    'failures',
    'easy',
]



def RunSteps(api: RecipeApi):
  api.cros_source.configure_builder(default_main=True)

  is_staging = api.m.cros_infra_config.is_staging
  with api.cros_source.checkout_overlays_context():
    api.cros_source.ensure_synced_cache(is_staging=is_staging,
                                        projects=['chromiumos/chromite'])
    api.cros_lkgm.cleanup_cls()


def GenTests(api: RecipeTestApi):

  def test(name: str, *args, **kwargs) -> TestData:
    return api.test(
        name,
        api.properties(
            **{
                '$chromeos/cros_lkgm': {
                    'enable_lkgm': kwargs.pop('enable_lkgm', True),
                    'full_run': kwargs.pop('full_run', True),
                },
            }), *args, **kwargs)

  yield test('cleanup')
  yield test('cleanup-staging', full_run=False)
  yield test('disabled-lkgm', enable_lkgm=False)
