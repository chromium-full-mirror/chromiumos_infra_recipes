# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_storage',
]



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

  api.assertions.assertEqual(
      expected_results['DLCImage'],
      len([x for x in images if isinstance(x, api.cros_storage.DLCImage)]))

  api.assertions.assertEqual(
      expected_results['FullPayload'],
      len([x for x in images if isinstance(x, api.cros_storage.FullPayload)]))

  api.assertions.assertEqual(
      expected_results['DeltaPayload'],
      len([x for x in images if isinstance(x, api.cros_storage.DeltaPayload)]))

  api.assertions.assertEqual(
      expected_results['FullDLCPayload'],
      len([x for x in images if isinstance(x, api.cros_storage.FullDLCPayload)
          ]))

  api.assertions.assertEqual(
      expected_results['DeltaDLCPayload'],
      len([
          x for x in images if isinstance(x, api.cros_storage.DeltaDLCPayload)
      ]))


def GenTests(api):
  normal_results = {
      'UnsignedImage': 2,
      'SignedImage': 1,
      'DLCImage': 0,
      'FullPayload': 2,
      'DeltaPayload': 3,
      'FullDLCPayload': 0,
      'DeltaDLCPayload': 0,
  }

  normal_results_2 = {
      'UnsignedImage': 2,
      'SignedImage': 1,
      'DLCImage': 1,
      'FullPayload': 2,
      'DeltaPayload': 3,
      'FullDLCPayload': 1,
      'DeltaDLCPayload': 1,
  }
  no_results = {
      'UnsignedImage': 0,
      'SignedImage': 0,
      'DLCImage': 0,
      'FullPayload': 0,
      'DeltaPayload': 0,
      'FullDLCPayload': 0,
      'DeltaDLCPayload': 0,
  }

  missing_results = {
      'UnsignedImage': 1,
      'SignedImage': 0,
      'DLCImage': 0,
      'FullPayload': 0,
      'DeltaPayload': 0,
      'FullDLCPayload': 0,
      'DeltaDLCPayload': 0,
  }

  yield api.test('basic', api.cros_storage.test_listing(),
                 api.properties(expected_results=normal_results))

  yield api.test(
      'basicer',
      api.cros_storage.test_listing(
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_TEXT),
      api.properties(expected_results=normal_results_2))

  yield api.test(
      'missing',
      api.cros_storage.test_listing(
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_MISSING_TEST),
      api.properties(expected_results=missing_results))

  yield api.test('no-images',
                 api.step_data('discover gs artifacts.gsutil list', retcode=1),
                 api.properties(expected_results=no_results))
