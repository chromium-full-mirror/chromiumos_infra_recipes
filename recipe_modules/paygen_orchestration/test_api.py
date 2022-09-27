# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to simplify testing Chrome OS recipes.

This module provides helpers to make testing Chrome OS recipes simpler and more
consistent.
"""

import os
from recipe_engine import recipe_test_api

from PB.chromite.api.payload import Build as Build_pb2
from PB.chromite.api.payload import DLCImage as DLCImage_pb2
from PB.chromite.api.payload import GenerationRequest as GenerationRequest_pb2
from PB.chromite.api.payload import SignedImage as SignedImage_pb2
from PB.chromite.api.payload import UnsignedImage as UnsignedImage_pb2
import PB.chromiumos.common as common_pb2
from PB.chromiumos.common import BuildTarget as BuildTarget_pb2
from PB.recipes.chromeos.paygen import AutoupdateTestConfig
from PB.recipe_modules.chromeos.paygen_orchestration.examples.test import GetRequestTestInputProperties


def _read_test_file(filename):
  """Read the content of a file in this directory.

  Args:
    filename (str): The basename of the file (located in this directory) to
        read.

  Returns:
    (str): The contents of the file.
  """
  with open(os.path.join(os.path.abspath(os.path.dirname(__file__)),
                         filename)) as f:
    return f.read().strip()


class PaygenOrchestrationTestApi(recipe_test_api.RecipeTestApi):
  """Helper class for testing Chrome OS Paygen Recipes."""

  EXAMPLE_PAYGEN_JSON = _read_test_file('test_paygen.json')
  NO_DELTA_PAYGEN_JSON = _read_test_file('test_no_deltas.json')

  EXAMPLE_EMPTY_JSON = "{}"
  EXAMPLE_NOT_EVEN_JSON = "dawiojdoiawjdioawjdow"
  ALL_EXAMPLE_JSONS = [
      EXAMPLE_PAYGEN_JSON, EXAMPLE_EMPTY_JSON, EXAMPLE_NOT_EVEN_JSON
  ]

  # Pull out useful configs for testing get_requests (and others).
  EXAMPLE_SINGLE_PAYGEN_CONFIG = _read_test_file('test_single_cfg.json')

  # The following examples are to be used in conjunction with the above.
  SIGNED_SRC = SignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13421.89.0',
          bucket='b', channel='stable-channel'),
      image_type=common_pb2.IMAGE_TYPE_RECOVERY,
  )

  SIGNED_SRC_IRRELEVANT = SignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13421.89.0',
          bucket='b', channel='beta-channel'),
      image_type=common_pb2.IMAGE_TYPE_TEST)

  SIGNED_TGT = SignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13425.90.0',
          bucket='b', channel='stable-channel'),
      image_type=common_pb2.IMAGE_TYPE_RECOVERY)

  UNSIGNED_SRC = UnsignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13421.89.0',
          bucket='b', channel='stable-channel'),
      milestone='86',
      image_type=common_pb2.IMAGE_TYPE_TEST,
  )

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

  UNSIGNED_RECOVERY_TGT = UnsignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13425.90.0',
          bucket='b', channel='stable-channel'),
      milestone='86',
      image_type=common_pb2.IMAGE_TYPE_RECOVERY,
  )

  @property
  def EXAMPLE_GEN_REQUESTS_DELTA_SIGNED(self):
    return [
        GenerationRequest_pb2(
            src_signed_image=self.SIGNED_SRC,
            tgt_signed_image=self.SIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=False,
            chroot=self.m.cros_sdk.chroot(),
        ),
        GenerationRequest_pb2(src_signed_image=self.SIGNED_SRC,
                              tgt_signed_image=self.SIGNED_TGT, bucket='b',
                              verify=True, dryrun=False,
                              chroot=self.m.cros_sdk.chroot(), minios=True)
    ]

  @property
  def EXAMPLE_GEN_REQUESTS_DELTA_UNSIGNED(self):
    return [
        GenerationRequest_pb2(
            src_unsigned_image=self.UNSIGNED_SRC,
            tgt_unsigned_image=self.UNSIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=False,
            chroot=self.m.cros_sdk.chroot(),
        ),
        GenerationRequest_pb2(src_unsigned_image=self.UNSIGNED_SRC,
                              tgt_unsigned_image=self.UNSIGNED_TGT, bucket='b',
                              verify=True, dryrun=False,
                              chroot=self.m.cros_sdk.chroot(), minios=True)
    ]

  @property
  def EXAMPLE_GEN_REQUEST_DELTA_DLC(self):
    return [
        GenerationRequest_pb2(
            src_dlc_image=self.DLC_SRC,
            tgt_dlc_image=self.DLC_TGT,
            bucket='b',
            verify=True,
            dryrun=False,
            chroot=self.m.cros_sdk.chroot(),
        )
    ]

  @property
  def EXAMPLE_GEN_REQUESTS_FULL_SIGNED(self):
    return [
        GenerationRequest_pb2(
            full_update=True,
            tgt_signed_image=self.SIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=True,
            chroot=self.m.cros_sdk.chroot(),
        ),
        GenerationRequest_pb2(full_update=True,
                              tgt_signed_image=self.SIGNED_TGT, bucket='b',
                              verify=True, dryrun=True,
                              chroot=self.m.cros_sdk.chroot(), minios=True)
    ]

  @property
  def EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED(self):
    return [
        GenerationRequest_pb2(
            full_update=True,
            tgt_unsigned_image=self.UNSIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=True,
            chroot=self.m.cros_sdk.chroot(),
        ),
        GenerationRequest_pb2(full_update=True,
                              tgt_unsigned_image=self.UNSIGNED_TGT, bucket='b',
                              verify=True, dryrun=True,
                              chroot=self.m.cros_sdk.chroot(), minios=True)
    ]

  @property
  def EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED_RECOVERY(self):
    return [
        GenerationRequest_pb2(
            full_update=True,
            tgt_unsigned_image=self.UNSIGNED_RECOVERY_TGT,
            bucket='b',
            verify=True,
            dryrun=True,
            chroot=self.m.cros_sdk.chroot(),
        ),
        GenerationRequest_pb2(full_update=True,
                              tgt_unsigned_image=self.UNSIGNED_RECOVERY_TGT,
                              bucket='b', verify=True, dryrun=True,
                              chroot=self.m.cros_sdk.chroot(), minios=True)
    ]

  @property
  def EXAMPLE_GEN_REQUEST_FULL_DLC(self):
    return [
        GenerationRequest_pb2(
            full_update=True,
            tgt_dlc_image=self.DLC_TGT,
            bucket='b',
            verify=True,
            dryrun=True,
            chroot=self.m.cros_sdk.chroot(),
        )
    ]

  @property
  def EXAMPLE_GEN_REQUESTS_DELTA_N2N(self):
    return [
        GenerationRequest_pb2(
            src_unsigned_image=self.UNSIGNED_TGT,
            tgt_unsigned_image=self.UNSIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=False,
            chroot=self.m.cros_sdk.chroot(),
        ),
        GenerationRequest_pb2(src_unsigned_image=self.UNSIGNED_TGT,
                              tgt_unsigned_image=self.UNSIGNED_TGT, bucket='b',
                              verify=True, dryrun=False,
                              chroot=self.m.cros_sdk.chroot(), minios=True)
    ]

  @property
  def EXAMPLE_GEN_REQUESTS(self):
    return [
        self.EXAMPLE_GEN_REQUEST_DELTA_DLC[0],
        self.EXAMPLE_GEN_REQUESTS_DELTA_SIGNED[0],
        self.EXAMPLE_GEN_REQUESTS_DELTA_UNSIGNED[0],
        self.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
        self.EXAMPLE_GEN_REQUESTS_FULL_SIGNED[0],
        self.EXAMPLE_GEN_REQUESTS_FULL_UNSIGNED[0],
        self.EXAMPLE_GEN_REQUESTS_DELTA_N2N[0],
    ]

  # Sample list of models that might be exported by GoldenEye.
  # Includes models that aren't configured for AU testing (ex. bruce).
  # Excludes some models that may be in a cfg's applicable_models (ex. mako).
  ALL_EXPORTED_MODELS = [
      "astronaut", "nasher360", "blue", "bruce", "lava", "whitetip", "santa",
      "blacktip360", "blacktiplte", "babymega", "robo", "nasher", "blacktip",
      "robo360", "rabbid", "babytiger", "epaulette"
  ]

  # Sample list of models that might be configured in GoldenEye for AU testing.
  # Compared to ALL_EXPORTED_MODELS, excludes the following:
  # babymega, blacktip360, blacktiplte, bruce, lava, nasher, robo360, whitetip.
  AU_TESTING_MODELS = [
      "astronaut", "nasher360", "blue", "santa", "robo", "blacktip", "rabbid",
      "babytiger", "epaulette"
  ]

  EXAMPLE_TEST_REQUEST_DELTA_OMAHA = AutoupdateTestConfig(
      delta_type='OMAHA',
      applicable_models=AU_TESTING_MODELS,
  )

  EXAMPLE_TEST_REQUEST_DELTA_FSI = AutoupdateTestConfig(
      delta_type='FSI',
      applicable_models=ALL_EXPORTED_MODELS,
  )

  EXAMPLE_TEST_REQUEST_FULL_N2N = AutoupdateTestConfig(
      src_version=UNSIGNED_TGT.build.version,
      src_channel=UNSIGNED_TGT.build.channel,
      delta_type='N2N',
      applicable_models=AU_TESTING_MODELS,
  )

  EXAMPLE_TEST_REQUEST_FULL_OMAHA = AutoupdateTestConfig(
      src_version='13421.89.0',
      src_channel='stable-channel',
      delta_type='OMAHA',
      applicable_models=AU_TESTING_MODELS,
  )

  EXAMPLE_TEST_REQUEST_DELTA_N2N = AutoupdateTestConfig(
      delta_type='N2N',
      applicable_models=AU_TESTING_MODELS,
  )

  BASIC_TEST_PROPS = {
      'payload_cfg': EXAMPLE_SINGLE_PAYGEN_CONFIG,
      'signed_srcs': [SIGNED_SRC],
      'signed_tgts': [SIGNED_TGT],
      'unsigned_srcs': [UNSIGNED_SRC],
      'unsigned_tgts': [UNSIGNED_TGT],
      'dlc_srcs': [DLC_SRC],
      'dlc_tgts': [DLC_TGT],
      'full_update': False,
  }

  def test_paygen(self, step_name, json_return):
    """Mock up step results for the GS cat."""
    test_response = self.m.step.step_data(
        step_name, stdout=self.m.raw_io.output(json_return))
    return test_response

  def props(self, api_props, request_type, expected_reqs, **kwargs):
    """Define a test prop from a request_type and incoming kwargs."""
    return api_props(
        GetRequestTestInputProperties(
            request_type=request_type, payload_cfg=kwargs['payload_cfg'],
            signed_srcs=kwargs['signed_srcs'],
            signed_tgts=kwargs['signed_tgts'],
            unsigned_srcs=kwargs['unsigned_srcs'],
            unsigned_tgts=kwargs['unsigned_tgts'], dlc_srcs=kwargs['dlc_srcs'],
            dlc_tgts=kwargs['dlc_tgts'], full_update=kwargs['full_update'],
            expected_reqs=expected_reqs))
