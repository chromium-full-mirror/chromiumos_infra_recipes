# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_storage',
]

from PB.chromite.api.payload import Build as Build_pb2
from PB.chromite.api.payload import SignedImage as SignedImage_pb2
from PB.chromite.api.payload import UnsignedImage as UnsignedImage_pb2
from PB.chromiumos.common import ImageType


def RunSteps(api):
  good_unsigned_image_uri = ('gs://test-bucket/canary-channel/zork/13337.0.1/'
                             'ChromeOS-recovery-R82-13337.0.1-zork.tar.xz')
  good_signed_image_uri = ('gs://test-bucket/canary-channel/zork/13337.0.1/'
                           'chromeos_13337.0.1_zork_recovery_canary_mp-v5.bin')
  good_dlc_image_uri = ('gs://test-bucket/canary-channel/zork/13337.0.1/'
                        'dlc/termina-dlc/package/dlc.img')

  test_artifact_root = api.cros_storage.ArtifactRoot('test-bucket',
                                                     'canary-channel', 'zork',
                                                     '13337.0.1')
  test_unsigned_image = (
      api.cros_storage.UnsignedImage(test_artifact_root,
                                     ImageType.Value('RECOVERY'), 'R82'))
  test_signed_image = (
      api.cros_storage.SignedImage(test_artifact_root,
                                   ImageType.Value('RECOVERY'), 'mp-v5'))
  test_dlc_image = (
      api.cros_storage.DLCImage(test_artifact_root, 'termina-dlc', 'package',
                                'dlc.img'))

  api.assertions.assertEqual(good_unsigned_image_uri, test_unsigned_image.uri)
  api.assertions.assertEqual(good_signed_image_uri, test_signed_image.uri)
  api.assertions.assertEqual(good_dlc_image_uri, test_dlc_image.uri)

  good_unsigned_full_payload_uri = (
      'gs://test-bucket/canary-channel/zork/13337.0.1/'
      'payloads/chromeos_13337.0.1_zork_canary-channel_full_test.bin-abc123')
  good_unsigned_delta_payload_uri = (
      'gs://test-bucket/canary-channel/zork/13337.0.1/'
      'payloads/chromeos_13336.0.1-13337.0.1_zork_canary-channel_delta_test.bin-abc123'
  )
  good_signed_full_payload_uri = (
      'gs://test-bucket/canary-channel/zork/13337.0.1/'
      'payloads/chromeos_13337.0.1_zork_canary-channel_full_mp-v5.bin-abc123.signed'
  )
  good_signed_delta_payload_uri = (
      'gs://test-bucket/canary-channel/zork/13337.0.1/'
      'payloads/chromeos_13336.0.1-13337.0.1_zork_canary-channel_delta_mp-v5.bin-abc123.signed'
  )

  src_test_artifact_root = api.cros_storage.ArtifactRoot(
      'test-bucket', 'canary-channel', 'zork', '13336.0.1')
  src_test_unsigned_image = (
      api.cros_storage.UnsignedImage(src_test_artifact_root,
                                     ImageType.Value('RECOVERY'), 'R82'))
  src_test_signed_image = (
      api.cros_storage.UnsignedImage(src_test_artifact_root,
                                     ImageType.Value('RECOVERY'), 'mp-v5'))
  unsigned_full_payload = api.cros_storage.FullPayload(test_unsigned_image,
                                                       'abc123')
  signed_full_payload = api.cros_storage.FullPayload(test_signed_image,
                                                     'abc123')
  unsigned_delta_payload = api.cros_storage.DeltaPayload(
      test_unsigned_image, src_test_unsigned_image, 'abc123')
  signed_delta_payload = api.cros_storage.DeltaPayload(test_signed_image,
                                                       src_test_signed_image,
                                                       'abc123')

  api.assertions.assertEqual(good_unsigned_full_payload_uri,
                             unsigned_full_payload.uri)
  api.assertions.assertEqual(good_signed_full_payload_uri,
                             signed_full_payload.uri)
  api.assertions.assertEqual(good_unsigned_delta_payload_uri,
                             unsigned_delta_payload.uri)
  api.assertions.assertEqual(good_signed_delta_payload_uri,
                             signed_delta_payload.uri)

  # Make a round trip from construction back to the uri.
  api.assertions.assertEqual(
      good_unsigned_image_uri,
      api.cros_storage.UnsignedImage.parse_uri(good_unsigned_image_uri).uri)

  api.assertions.assertEqual(
      good_signed_image_uri,
      api.cros_storage.SignedImage.parse_uri(good_signed_image_uri).uri)

  api.assertions.assertEqual(
      good_dlc_image_uri,
      api.cros_storage.DLCImage.parse_uri(good_dlc_image_uri).uri)

  api.assertions.assertEqual(
      good_unsigned_full_payload_uri,
      api.cros_storage.FullPayload.parse_uri(
          good_unsigned_full_payload_uri).uri)

  api.assertions.assertEqual(
      good_unsigned_delta_payload_uri,
      api.cros_storage.DeltaPayload.parse_uri(
          good_unsigned_delta_payload_uri).uri)

  api.assertions.assertEqual(
      good_signed_full_payload_uri,
      api.cros_storage.FullPayload.parse_uri(good_signed_full_payload_uri).uri)

  api.assertions.assertEqual(
      good_signed_delta_payload_uri,
      api.cros_storage.DeltaPayload.parse_uri(
          good_signed_delta_payload_uri).uri)

  # Ensure None returns on unmatched input.
  api.assertions.assertIsNone(
      api.cros_storage.SignedImage.parse_uri(
          'gs://nonsense/somestuff/and/others'))
  api.assertions.assertIsNone(
      api.cros_storage.UnsignedImage.parse_uri('gs://crumbos/nonsense'))
  api.assertions.assertIsNone(
      api.cros_storage.DLCImage.parse_uri('gs://crumbos/nonsense/downloadable'))
  api.assertions.assertIsNone(
      api.cros_storage.DeltaPayload.parse_uri('gs://crumbos/nonsense'))
  api.assertions.assertIsNone(
      api.cros_storage.FullPayload.parse_uri('gs://crumbos/nonsense'))

  # Ensure close results even return None.
  api.assertions.assertIsNone(
      api.cros_storage.SignedImage.parse_uri(good_signed_image_uri[:-1]))
  api.assertions.assertIsNone(
      api.cros_storage.UnsignedImage.parse_uri(good_unsigned_image_uri[:-1]))

  # Split off the dlc.img part of the path.
  bad_dlc_image_uri = '/'.join(good_dlc_image_uri.split('/')[:-1])
  api.assertions.assertIsNone(
      api.cros_storage.DLCImage.parse_uri(bad_dlc_image_uri))

  with api.assertions.assertRaises(
      api.cros_storage.UnsupportedImageTypeException):
    api.cros_storage.SignedImage(test_artifact_root, ImageType.Value('DEV'),
                                 'mp-v2')

  # Make protos out of them.
  test_unsigned_image.to_proto()
  test_signed_image.to_proto()
  test_dlc_image.to_proto()


def GenTests(api):
  yield (api.test('basic'))
