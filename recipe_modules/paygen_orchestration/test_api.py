# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to simplify testing CrOS recipes.

This module provides helpers to make testing CrOS recipes simpler and more
consistent.
"""

import json
from typing import Callable, List

from RECIPE_MODULES.chromeos.util.util import read_test_file

import PB.chromiumos.common as common_pb2
from PB.chromite.api.payload import Build as Build_pb2
from PB.chromite.api.payload import DLCImage as DLCImage_pb2
from PB.chromite.api.payload import GenerationRequest
from PB.chromite.api.payload import SignedImage as SignedImage_pb2
from PB.chromite.api.payload import UnsignedImage as UnsignedImage_pb2
from PB.chromiumos.common import BuildTarget as BuildTarget_pb2
from PB.recipe_modules.chromeos.paygen_orchestration.examples.test import GetRequestTestInputProperties
from recipe_engine import recipe_test_api
from recipe_engine.recipe_test_api import TestData


def _example_big_config() -> str:
  """Multiply paygen config for summary markdown truncate testing."""
  data = json.loads(read_test_file('test_paygen.json', __file__))
  # 99 total.
  data['delta'] = data['delta'] * 33
  return json.dumps(data)


class PaygenOrchestrationTestApi(recipe_test_api.RecipeTestApi):
  """Helper class for testing CrOS Paygen Recipes."""

  EXAMPLE_PAYGEN_JSON = read_test_file('test_paygen.json', __file__)
  NO_DELTA_PAYGEN_JSON = read_test_file('test_no_deltas.json', __file__)

  EXAMPLE_PAYGEN_JSON_BIG = _example_big_config()

  EXAMPLE_EMPTY_JSON = '{}'
  EXAMPLE_NOT_EVEN_JSON = 'dawiojdoiawjdioawjdow'
  ALL_EXAMPLE_JSONS = [
      EXAMPLE_PAYGEN_JSON, EXAMPLE_EMPTY_JSON, EXAMPLE_NOT_EVEN_JSON
  ]

  # Pull out useful configs for testing get_requests (and others).
  EXAMPLE_SINGLE_PAYGEN_CONFIG = read_test_file('test_single_cfg.json',
                                                __file__)

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

  def get_example_gen_requests_delta_signed(
      self, minios=True) -> List[GenerationRequest]:
    ret = [
        GenerationRequest(
            src_signed_image=self.SIGNED_SRC,
            tgt_signed_image=self.SIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=False,
            chroot=self.m.cros_sdk.chroot(),
        )
    ]
    if minios:
      ret.append(
          GenerationRequest(
              src_signed_image=self.SIGNED_SRC,
              tgt_signed_image=self.SIGNED_TGT,
              bucket='b',
              verify=True,
              dryrun=False,
              chroot=self.m.cros_sdk.chroot(),
              minios=True,
          ))
    return ret

  @property
  def EXAMPLE_GEN_REQUESTS_DELTA_UNSIGNED(self) -> List[GenerationRequest]:
    return [
        GenerationRequest(
            src_unsigned_image=self.UNSIGNED_SRC,
            tgt_unsigned_image=self.UNSIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=False,
            chroot=self.m.cros_sdk.chroot(),
        ),
        GenerationRequest(
            src_unsigned_image=self.UNSIGNED_SRC,
            tgt_unsigned_image=self.UNSIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=False,
            chroot=self.m.cros_sdk.chroot(),
            minios=True,
        )
    ]

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

  def get_example_gen_requests_full_signed(
      self, minios=True) -> List[GenerationRequest]:
    ret = [
        GenerationRequest(
            full_update=True,
            tgt_signed_image=self.SIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=True,
            chroot=self.m.cros_sdk.chroot(),
        )
    ]
    if minios:
      ret.append(
          GenerationRequest(
              full_update=True,
              tgt_signed_image=self.SIGNED_TGT,
              bucket='b',
              verify=True,
              dryrun=True,
              chroot=self.m.cros_sdk.chroot(),
              minios=True,
          ))
    return ret

  def get_example_gen_requests_full_unsigned(
      self, minios=True) -> List[GenerationRequest]:
    ret = [
        GenerationRequest(
            full_update=True,
            tgt_unsigned_image=self.UNSIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=True,
            chroot=self.m.cros_sdk.chroot(),
        )
    ]
    if minios:
      ret.append(
          GenerationRequest(
              full_update=True,
              tgt_unsigned_image=self.UNSIGNED_TGT,
              bucket='b',
              verify=True,
              dryrun=True,
              chroot=self.m.cros_sdk.chroot(),
              minios=True,
          ))
    return ret

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

  def get_example_gen_requests_delta_n2n(
      self, minios=True) -> List[GenerationRequest]:
    ret = [
        GenerationRequest(
            src_unsigned_image=self.UNSIGNED_TGT,
            tgt_unsigned_image=self.UNSIGNED_TGT,
            bucket='b',
            verify=True,
            dryrun=False,
            chroot=self.m.cros_sdk.chroot(),
        )
    ]
    if minios:
      ret.append(
          GenerationRequest(
              src_unsigned_image=self.UNSIGNED_TGT,
              tgt_unsigned_image=self.UNSIGNED_TGT,
              bucket='b',
              verify=True,
              dryrun=False,
              chroot=self.m.cros_sdk.chroot(),
              minios=True,
          ))
    return ret

  @property
  def EXAMPLE_GEN_REQUESTS(self) -> List[GenerationRequest]:
    return [
        self.EXAMPLE_GEN_REQUEST_DELTA_DLC[0],
        self.get_example_gen_requests_delta_signed()[0],
        self.EXAMPLE_GEN_REQUESTS_DELTA_UNSIGNED[0],
        self.EXAMPLE_GEN_REQUEST_FULL_DLC[0],
        self.get_example_gen_requests_full_signed()[0],
        self.get_example_gen_requests_full_unsigned()[0],
        self.get_example_gen_requests_delta_n2n()[0],
    ]

  # Sample list of models that might be exported by GoldenEye.
  # Includes models that aren't configured for AU testing (ex. bruce).
  # Excludes some models that may be in a cfg's applicable_models (ex. mako).
  ALL_EXPORTED_MODELS = [
      'astronaut', 'nasher360', 'blue', 'bruce', 'lava', 'whitetip', 'santa',
      'blacktip360', 'blacktiplte', 'babymega', 'robo', 'nasher', 'blacktip',
      'robo360', 'rabbid', 'babytiger', 'epaulette'
  ]

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

  def test_paygen(self, step_name: str, json_return: str) -> TestData:
    """Mock up step results for the GS cat."""
    test_response = self.m.step.step_data(
        step_name, stdout=self.m.raw_io.output(json_return))
    return test_response

  def props(self,
            api_props: Callable[[GetRequestTestInputProperties], TestData],
            request_type: GetRequestTestInputProperties.GetRequestType,
            expected_reqs: List[GenerationRequest], **kwargs) -> TestData:
    """Define a test prop from a request_type and incoming kwargs."""
    return api_props(
        GetRequestTestInputProperties(
            request_type=request_type, payload_cfg=kwargs['payload_cfg'],
            signed_srcs=kwargs['signed_srcs'],
            signed_tgts=kwargs['signed_tgts'],
            unsigned_srcs=kwargs['unsigned_srcs'],
            unsigned_tgts=kwargs['unsigned_tgts'], dlc_srcs=kwargs['dlc_srcs'],
            dlc_tgts=kwargs['dlc_tgts'], full_update=kwargs['full_update'],
            no_minios=kwargs.get('no_minios',
                                 False), expected_reqs=expected_reqs))
