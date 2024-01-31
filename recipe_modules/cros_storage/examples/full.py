# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.common import ImageType

DEPS = [
    'recipe_engine/assertions',
    'cros_storage',
]



def RunSteps(api):
  good_unsigned_image_uri = ('gs://test-bucket/canary-channel/zork/13337.0.1/'
                             'ChromeOS-recovery-R82-13337.0.1-zork.tar.xz')
  good_unsigned_image_archive_uri = (
      'gs://chromeos-image-archive/zork-release/R82-13337.0.1')
  good_signed_image_uri = ('gs://test-bucket/canary-channel/zork/13337.0.1/'
                           'chromeos_13337.0.1_zork_recovery_canary_mp-v5.bin')
  good_dlc_image_uri = ('gs://test-bucket/canary-channel/zork/13337.0.1/'
                        'dlc/termina-dlc/package/dlc.img')

  test_artifact_root = api.cros_storage.ArtifactRoot('test-bucket',
                                                     'canary-channel', 'zork',
                                                     '13337.0.1')
  test_unsigned_image = (
      api.cros_storage.UnsignedImage(test_artifact_root,
                                     ImageType.Value('IMAGE_TYPE_RECOVERY'),
                                     'R82'))
  test_signed_image = (
      api.cros_storage.SignedImage(test_artifact_root,
                                   ImageType.Value('IMAGE_TYPE_RECOVERY'),
                                   'mp-v5'))
  test_dlc_image = (
      api.cros_storage.DLCImage(test_artifact_root, 'termina-dlc', 'package',
                                'dlc.img'))
  test_dlc_image_2 = (
      api.cros_storage.DLCImage(test_artifact_root, 'sample-dlc', 'package',
                                'dlc.img'))
  api.assertions.assertFalse(
      api.cros_storage.DLCImage.compatible(test_dlc_image.to_proto(),
                                           test_dlc_image_2.to_proto()))

  api.assertions.assertEqual(good_unsigned_image_uri, test_unsigned_image.uri)
  api.assertions.assertEqual(good_unsigned_image_archive_uri,
                             test_unsigned_image.archive_uri)
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
  good_delta_dlc_payload_uri = (
      'gs://test-bucket/canary-channel/zork/13337.0.1/'
      'payloads/dlc/termina-dlc/package/'
      'dlc_termina-dlc_package_13336.0.1-13337.0.1_zork_canary-channel_delta.bin-gvtgcmjugztghjioi4bbf32rlvybuioo.signed'
  )
  good_full_dlc_payload_uri = (
      'gs://test-bucket/canary-channel/zork/13337.0.1/'
      'payloads/dlc/termina-dlc/package/'
      'dlc_termina-dlc_package_13337.0.1_zork_canary-channel_full.bin-gvtgcmjugztghuefrdqmdn2x56si2xej.signed'
  )

  src_test_artifact_root = api.cros_storage.ArtifactRoot(
      'test-bucket', 'canary-channel', 'zork', '13336.0.1')
  src_test_unsigned_image = (
      api.cros_storage.UnsignedImage(src_test_artifact_root,
                                     ImageType.Value('IMAGE_TYPE_RECOVERY'),
                                     'R82'))
  src_test_signed_image = (
      api.cros_storage.UnsignedImage(src_test_artifact_root,
                                     ImageType.Value('IMAGE_TYPE_RECOVERY'),
                                     'mp-v5'))
  src_test_dlc_image = (
      api.cros_storage.DLCImage(src_test_artifact_root, 'termina-dlc',
                                'package', 'gvtgcmjugztghjioi4bbf32rlvybuioo'))

  unsigned_full_payload = api.cros_storage.FullPayload(test_unsigned_image,
                                                       'abc123')
  signed_full_payload = api.cros_storage.FullPayload(test_signed_image,
                                                     'abc123')
  unsigned_delta_payload = api.cros_storage.DeltaPayload(
      test_unsigned_image, src_test_unsigned_image, 'abc123')
  signed_delta_payload = api.cros_storage.DeltaPayload(test_signed_image,
                                                       src_test_signed_image,
                                                       'abc123')

  delta_dlc_payload = api.cros_storage.DeltaDLCPayload(
      test_dlc_image, src_test_dlc_image, 'gvtgcmjugztghjioi4bbf32rlvybuioo')
  full_dlc_payload = api.cros_storage.FullDLCPayload(
      test_dlc_image, 'gvtgcmjugztghuefrdqmdn2x56si2xej')

  api.assertions.assertEqual(good_unsigned_full_payload_uri,
                             unsigned_full_payload.uri)
  api.assertions.assertEqual(good_signed_full_payload_uri,
                             signed_full_payload.uri)
  api.assertions.assertEqual(good_unsigned_delta_payload_uri,
                             unsigned_delta_payload.uri)
  api.assertions.assertEqual(good_signed_delta_payload_uri,
                             signed_delta_payload.uri)
  api.assertions.assertEqual(good_delta_dlc_payload_uri, delta_dlc_payload.uri)
  api.assertions.assertEqual(good_full_dlc_payload_uri, full_dlc_payload.uri)

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

  api.assertions.assertEqual(
      good_delta_dlc_payload_uri,
      api.cros_storage.DeltaDLCPayload.parse_uri(
          good_delta_dlc_payload_uri).uri)

  api.assertions.assertEqual(
      good_full_dlc_payload_uri,
      api.cros_storage.FullDLCPayload.parse_uri(good_full_dlc_payload_uri).uri)

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
  api.assertions.assertIsNone(
      api.cros_storage.DeltaDLCPayload.parse_uri('gs://crumbos/nonsense'))
  api.assertions.assertIsNone(
      api.cros_storage.FullDLCPayload.parse_uri('gs://crumbos/nonsense'))

  # Ensure close results even return None.
  api.assertions.assertIsNone(
      api.cros_storage.SignedImage.parse_uri(good_signed_image_uri[:-1]))
  api.assertions.assertIsNone(
      api.cros_storage.UnsignedImage.parse_uri(good_unsigned_image_uri[:-1]))
  api.assertions.assertIsNone(
      api.cros_storage.DeltaDLCPayload.parse_uri(good_delta_dlc_payload_uri +
                                                 '.json'))
  api.assertions.assertIsNone(
      api.cros_storage.FullDLCPayload.parse_uri(good_full_dlc_payload_uri +
                                                '.json'))
  # Split off the dlc.img part of the path.
  bad_dlc_image_uri = '/'.join(good_dlc_image_uri.split('/')[:-1])
  api.assertions.assertIsNone(
      api.cros_storage.DLCImage.parse_uri(bad_dlc_image_uri))

  with api.assertions.assertRaises(
      api.cros_storage.UnsupportedImageTypeException):
    api.cros_storage.SignedImage(test_artifact_root,
                                 ImageType.Value('IMAGE_TYPE_DEV'), 'mp-v2')

  # Make protos out of them.
  test_unsigned_image.to_proto()
  test_signed_image.to_proto()
  test_dlc_image.to_proto()


def GenTests(api):
  yield api.test('basic')
