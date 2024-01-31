# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test to verify install_packages is called prior to look_up_builder_metadata."""

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'build_menu',
    'builder_metadata',
]



def RunSteps(api):
  with api.step.nest('expect failure'):
    api.build_menu.packages_installed = False
    with api.assertions.assertRaises(api.step.StepFailure):
      api.builder_metadata.look_up_builder_metadata()
  with api.step.nest('expect success'):
    api.build_menu.packages_installed = True
    api.builder_metadata.look_up_builder_metadata()


def GenTests(api):

  yield api.test('install-packages-verified')
