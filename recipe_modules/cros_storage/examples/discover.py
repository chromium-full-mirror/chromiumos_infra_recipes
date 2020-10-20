# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['recipe_engine/assertions', 'cros_storage']

from PB.chromiumos.common import ImageType


def RunSteps(api):
  images = api.cros_storage.DiscoverGSArtifacts(
      'gs://fake-releases/canary-channel/coral/13337.1.0')

  api.assertions.assertEqual(
      1,
      len([x for x in images if isinstance(x, api.cros_storage.UnsignedImage)]))

  api.assertions.assertEqual(
      1,
      len([x for x in images if isinstance(x, api.cros_storage.SignedImage)]))


def GenTests(api):
  yield (api.test('basic') + api.cros_storage.normal_test_data())
