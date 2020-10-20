# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['recipe_engine/assertions', 'cros_storage']

from PB.chromiumos.common import ImageType


def RunSteps(api):
  good_unsigned_uri = 'gs://test-bucket/canary/zork/13337.0.1/ChromeOS-recovery-R82-13337.0.1-zork.tar.xz'
  good_signed_uri = 'gs://test-bucket/canary/zork/13337.0.1/chromeos_13337.0.1_zork_recovery_canary_mp-v5.bin'

  test_artifact_root = api.cros_storage.ArtifactRoot('test-bucket', 'canary',
                                                     'zork', '13337.0.1')
  test_unsigned_image = (
      api.cros_storage.UnsignedImage(test_artifact_root,
                                     ImageType.Value('RECOVERY'), 'R82'))
  test_signed_image = (
      api.cros_storage.SignedImage(test_artifact_root,
                                   ImageType.Value('RECOVERY'), 'mp-v5'))

  api.assertions.assertEqual(good_unsigned_uri, test_unsigned_image.uri)
  api.assertions.assertEqual(good_signed_uri, test_signed_image.uri)

  # Make a round trip from construction back to the uri.
  api.assertions.assertEqual(
      good_unsigned_uri,
      api.cros_storage.UnsignedImage.ParseUri(good_unsigned_uri).uri)

  api.assertions.assertEqual(
      good_signed_uri,
      api.cros_storage.SignedImage.ParseUri(good_signed_uri).uri)

  # Ensure None returns on unmatched input.
  api.assertions.assertIsNone(
      api.cros_storage.SignedImage.ParseUri(
          'gs://nonsense/somestuff/and/others'))
  api.assertions.assertIsNone(
      api.cros_storage.UnsignedImage.ParseUri('gs://crumbos/nonsense'))

  # Ensure close results even return None.
  api.assertions.assertIsNone(
      api.cros_storage.SignedImage.ParseUri(good_signed_uri[:-1]))
  api.assertions.assertIsNone(
      api.cros_storage.UnsignedImage.ParseUri(good_unsigned_uri[:-1]))

  with api.assertions.assertRaises(
      api.cros_storage.UnsupportedImageTypeException):
    api.cros_storage.SignedImage(test_artifact_root, ImageType.Value('DEV'),
                                 'mp-v2')


def GenTests(api):
  yield (api.test('basic'))
