# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to simplify testing CrOS recipes.

This module provides helpers to make testing CrOS recipes simpler and more
consistent.
"""
from typing import List

import PB.chromiumos.common as common_pb2
from PB.chromite.api.payload import Build as Build_pb2
from PB.chromite.api.payload import DLCImage as DLCImage_pb2
from PB.chromite.api.payload import GenerationRequest
from PB.chromite.api.payload import SignedImage as SignedImage_pb2
from PB.chromite.api.payload import UnsignedImage as UnsignedImage_pb2
from PB.chromiumos.common import BuildTarget as BuildTarget_pb2
from recipe_engine import recipe_test_api

TEST_TARGET_TEST_REQUIREMENTS_DATA = b'''{
    "perTargetTestRequirements": [
        {
            "targetCriteria": {
                "buildTarget": "atlas-kernelnext",
                "builderName": "atlas-kernelnext-release-main"
            },
            "hwTestCfg": {
                "hwTest": [
                    {
                        "common": {
                            "displayName": "atlas-kernelnext-release-main.hw.bvt-tast-cq",
                            "critical": false,
                            "testSuiteGroups": [
                                {
                                    "testSuiteGroup": "default-tast-suites"
                                }
                            ]
                        },
                        "suite": "bvt-tast-cq",
                        "skylabBoard": "atlas",
                        "hwTestSuiteType": "TAST",
                        "pool": "DUT_POOL_QUOTA"
                    }
                ]
            }
        },
        {
            "targetCriteria": {
                "buildTarget": "zork",
                "builderName": "zork-release-main"
            },
            "hwTestCfg": {
                "hwTest": [
                    {
                        "common": {
                            "displayName": "zork-release-main.hw.bvt-tast-cq",
                            "critical": false,
                            "testSuiteGroups": [
                                {
                                    "testSuiteGroup": "default-tast-suites"
                                }
                            ]
                        },
                        "suite": "bvt-tast-cq",
                        "skylabBoard": "zork",
                        "hwTestSuiteType": "TAST",
                        "pool": "DUT_POOL_QUOTA"
                    }
                ]
            }
        }
    ]
}'''


class PaygenTestingTestApi(recipe_test_api.RecipeTestApi):
  """Helper class for testing CrOS Paygen Recipes."""

  TEST_TARGET_TEST_REQUIREMENTS_DATA = TEST_TARGET_TEST_REQUIREMENTS_DATA

  SIGNED_SRC = SignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13421.89.0',
          bucket='b', channel='stable-channel'),
      image_type=common_pb2.IMAGE_TYPE_RECOVERY,
  )

  SIGNED_TGT = SignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13425.90.0',
          bucket='b', channel='stable-channel'),
      image_type=common_pb2.IMAGE_TYPE_RECOVERY)

  UNSIGNED_TGT = UnsignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13425.90.0',
          bucket='b', channel='stable-channel'),
      milestone='86',
      image_type=common_pb2.IMAGE_TYPE_TEST,
  )

  DLC_SRC = DLCImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13421.89.0',
          bucket='b', channel='stable-channel'),
      dlc_id='termina-dlc',
      dlc_package='package',
      dlc_image='dlc.img',
  )

  DLC_TGT = DLCImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13425.90.0',
          bucket='b', channel='stable-channel'),
      dlc_id='termina-dlc',
      dlc_package='package',
      dlc_image='dlc.img',
  )

  @property
  def EXAMPLE_GEN_REQUEST_DELTA_DLC(self) -> List[GenerationRequest]:
    return [
        GenerationRequest(
            src_dlc_image=self.DLC_SRC,
            tgt_dlc_image=self.DLC_TGT,
            bucket='b',
            verify=True,
            dryrun=False,
            chroot=self.m.cros_sdk.chroot(),
        )
    ]

  @property
  def EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED(self) -> List[GenerationRequest]:
    return [
        GenerationRequest(
            full_update=True,
            tgt_unsigned_image=self.UNSIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=True,
            chroot=self.m.cros_sdk.chroot(),
        ),
        GenerationRequest(
            full_update=True,
            tgt_unsigned_image=self.UNSIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=True,
            chroot=self.m.cros_sdk.chroot(),
            minios=True,
        )
    ]

  @property
  def EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED_NO_DRYRUN(self
                                                  ) -> List[GenerationRequest]:
    return [
        GenerationRequest(
            full_update=True,
            tgt_unsigned_image=self.UNSIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=False,
            chroot=self.m.cros_sdk.chroot(),
        )
    ]

  @property
  def EXAMPLE_GEN_REQUEST_FULL_DLC(self) -> List[GenerationRequest]:
    return [
        GenerationRequest(
            full_update=True,
            tgt_dlc_image=self.DLC_TGT,
            bucket='b',
            verify=True,
            dryrun=True,
            chroot=self.m.cros_sdk.chroot(),
        )
    ]

  @property
  def EXAMPLE_GEN_REQUESTS_DELTA_N2N(self) -> List[GenerationRequest]:
    return [
        GenerationRequest(
            src_unsigned_image=self.UNSIGNED_TGT,
            tgt_unsigned_image=self.UNSIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=False,
            chroot=self.m.cros_sdk.chroot(),
        ),
        GenerationRequest(
            src_unsigned_image=self.UNSIGNED_TGT,
            tgt_unsigned_image=self.UNSIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=False,
            chroot=self.m.cros_sdk.chroot(),
            minios=True,
        )
    ]

  @property
  def EXAMPLE_GEN_REQUESTS_DELTA_SIGNED(self) -> List[GenerationRequest]:
    return [
        GenerationRequest(
            src_signed_image=self.SIGNED_SRC,
            tgt_signed_image=self.SIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=False,
            chroot=self.m.cros_sdk.chroot(),
        ),
        GenerationRequest(
            src_signed_image=self.SIGNED_SRC,
            tgt_signed_image=self.SIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=False,
            chroot=self.m.cros_sdk.chroot(),
            minios=True,
        )
    ]
