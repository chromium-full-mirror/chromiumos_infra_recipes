# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_storage',
]

from PB.chromiumos.common import ImageType


def RunSteps(api):
  expected_results = api.properties.get('expected_results')
  images = api.cros_storage.discover_gs_artifacts(
      'gs://fake-releases/canary-channel/coral/13337.1.0')

  api.assertions.assertEqual(
      expected_results['UnsignedImage'],
      len([x for x in images if isinstance(x, api.cros_storage.UnsignedImage)]))

  api.assertions.assertEqual(
      expected_results['SignedImage'],
      len([x for x in images if isinstance(x, api.cros_storage.SignedImage)]))


def GenTests(api):
  normal_results = {
      'UnsignedImage': 2,
      'SignedImage': 1,
  }

  no_results = {
      'UnsignedImage': 0,
      'SignedImage': 0,
  }

  missing_results = {
      'UnsignedImage': 1,
      'SignedImage': 0,
  }

  yield api.test('basic-src', api.cros_storage.test_listing(),
                 api.properties(expected_results=normal_results))

  yield api.test(
      'basic-tgt',
      api.cros_storage.test_listing(
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_TEXT),
      api.properties(expected_results=normal_results))

  yield api.test(
      'missing-tgt',
      api.cros_storage.test_listing(
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_MISSING_TEST),
      api.properties(expected_results=missing_results))

  yield api.test('no-images',
                 api.step_data('discover gs artifacts.gsutil list', retcode=1),
                 api.properties(expected_results=no_results))
