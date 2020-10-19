# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['recipe_engine/assertions', 'cros_storage']

from PB.chromiumos.common import ImageType


def RunSteps(api):
  test_artifact_root = api.cros_storage.ArtifactRoot('test-bucket', 'canary',
                                                     'zork', '13337.0.1')
  test_unsigned_image = (
      api.cros_storage.UnsignedImage(test_artifact_root,
                                     ImageType.Value('RECOVERY'), '82'))
  test_signed_image = (
      api.cros_storage.SignedImage(test_artifact_root,
                                   ImageType.Value('RECOVERY'), 'mp-v5'))

  api.assertions.assertEqual(
      'gs://test-bucket/canary/zork/13337.0.1/ChromeOS-recovery-82-13337.0.1-zork.tar.xz',
      test_unsigned_image.uri)
  api.assertions.assertEqual(
      'gs://test-bucket/canary/zork/13337.0.1/chromeos_13337.0.1_zork_recovery_canary_mp-v5.bin',
      test_signed_image.uri)

  with api.assertions.assertRaises(
      api.cros_storage.UnsupportedImageTypeException):
    api.cros_storage.SignedImage(test_artifact_root, ImageType.Value('DEV'),
                                 'mp-v2')


def GenTests(api):
  yield (api.test('basic'))
