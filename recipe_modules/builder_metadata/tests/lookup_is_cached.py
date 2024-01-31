# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to verify that builder_metadata is properly cached between invocations."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'build_menu',
    'builder_metadata',
]



def RunSteps(api):
  api.build_menu.packages_installed = True
  with api.step.nest('first-lookup'):
    first_metadata = api.builder_metadata.look_up_builder_metadata()
  with api.step.nest('second-lookup'):
    second_result = api.builder_metadata.look_up_builder_metadata()
  api.assertions.assertEqual(first_metadata, second_result)


def GenTests(api):

  yield api.test(
      'two-lookups-second-cached',
      api.builder_metadata.mock_metadata('first-lookup'),
      api.post_check(post_process.MustRun,
                     'first-lookup.look up builder metadata'),
      api.post_check(post_process.MustRun,
                     ('first-lookup.look up builder metadata.call chromite.api.'
                      'PackageService/GetBuilderMetadata')),
      api.post_check(post_process.MustRun,
                     'second-lookup.look up builder metadata'),
      api.post_check(
          # Because cached the build-api is *not* hit here.
          post_process.DoesNotRun,
          ('second-lookup.look up builder metadata.call chromite.api.'
           'PackageService/GetBuilderMetadata')))
