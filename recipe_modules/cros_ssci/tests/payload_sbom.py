# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests generate_payload_sbom and _to_payload_description."""

from recipe_engine import post_process

from PB.chromite.api.payload import Build, DLCImage, GenerationRequest, SignedImage, UnsignedImage
from PB.chromiumos import common as common_pb2
from RECIPE_MODULES.chromeos.cros_ssci.api import _to_payload_description

DEPS = [
    'cros_ssci',
    'test_util',
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
]
_TEST_BUILD_TARGET = common_pb2.BuildTarget(name='kukui')

_TEST_CASES = [
    (
        GenerationRequest(
            full_update=True,
            tgt_signed_image=SignedImage(
                image_type=common_pb2.IMAGE_TYPE_BASE,
                key='sample_key',
                build=Build(
                    channel='stable',
                    version='1.2.3',
                    build_target=_TEST_BUILD_TARGET,
                ),
            ),
        ),
        'SignedImage kukui IMAGE_TYPE_BASE: full_update -> stable 1.2.3 sample_key',
    ),
    (
        GenerationRequest(
            tgt_unsigned_image=UnsignedImage(
                image_type=common_pb2.IMAGE_TYPE_TEST,
                milestone='M120',
                build=Build(
                    channel='dev',
                    version='2.0.0',
                    build_target=_TEST_BUILD_TARGET,
                ),
            ),
            src_unsigned_image=UnsignedImage(
                milestone='M119',
                build=Build(
                    channel='dev',
                    version='1.0.0',
                ),
            ),
        ),
        'UnsignedImage kukui IMAGE_TYPE_TEST: dev 1.0.0 M119 -> dev 2.0.0 M120',
    ),
    (
        GenerationRequest(
            tgt_dlc_image=DLCImage(
                image_type=common_pb2.IMAGE_TYPE_DLC,
                dlc_id='my_dlc',
                dlc_package='package_a',
                dlc_image='dlc.img',
                build=Build(
                    channel='stable',
                    version='3.0.0',
                    build_target=_TEST_BUILD_TARGET,
                ),
            ),
            src_dlc_image=DLCImage(
                build=Build(
                    channel='stable',
                    version='2.9.0',
                ),
            ),
        ),
        'DLCImage kukui IMAGE_TYPE_DLC my_dlc package_a dlc.img: stable 2.9.0 -> stable 3.0.0',
    ),
]


def RunSteps(api):
  for req, expected_desc in _TEST_CASES:
    desc = _to_payload_description(req)
    api.assertions.assertEqual(desc, expected_desc)

  # Use the first input to test generate_payload_sbom
  first_req = _TEST_CASES[0][0]
  out_path = api.path.mkdtemp() / 'payload.spdx.json'
  api.cros_ssci.generate_payload_sbom(first_req, out_path)


def GenTests(api):
  yield api.test(
      'basic',
      api.test_util.test_child_build(
          'kukui',
          builder_name='kukui-release-main',
          git_repo='https://chrome-internal.googlesource.com/chromeos/manifest-internal',
      ).build,
      api.post_check(post_process.StepSuccess, 'generate Payload SBOM'),
      api.post_process(post_process.DropExpectation),
  )
