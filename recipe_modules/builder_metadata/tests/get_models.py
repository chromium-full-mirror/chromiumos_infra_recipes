# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to verify builder_metadata.get_models."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'build_menu',
    'builder_metadata',
]



def RunSteps(api):
  api.build_menu.packages_installed = True
  # Test model metadata comes from the test response for
  # cros_build_api.PackageService.GetBuilderMetadata().
  models = api.builder_metadata.get_models()
  api.assertions.assertEqual(models, ['eve'])


def GenTests(api):

  yield api.test(
      'pulls-models-from-metadata', api.builder_metadata.mock_metadata(),
      api.post_check(post_process.MustRun,
                     ('look up builder metadata.call chromite.api.'
                      'PackageService/GetBuilderMetadata')))
