# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to simplify testing Chrome OS recipes.

This module provides helpers to make testing Chrome OS recipes simpler and more
consistent.
"""

import json
import os
from google.protobuf.json_format import MessageToJson
from recipe_engine import recipe_test_api

from PB.chromite.api.payload import Build as Build_pb2
from PB.chromite.api.payload import DLCImage as DLCImage_pb2
from PB.chromite.api.payload import GenerationRequest as GenerationRequest_pb2
from PB.chromite.api.payload import SignedImage as SignedImage_pb2
from PB.chromite.api.payload import UnsignedImage as UnsignedImage_pb2
import PB.chromiumos.common as common_pb2
from PB.chromiumos.common import BuildTarget as BuildTarget_pb2
from PB.recipe_modules.chromeos.cros_paygen.examples.test import GetRequestTestInputProperties


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


class PaygenTestApi(recipe_test_api.RecipeTestApi):
  """Helper class for testing Chrome OS Paygen Recipes."""

  EXAMPLE_PAYGEN_JSON = _read_test_file('test_paygen.json')
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
          bucket='b', channel='stable'),
      image_type=common_pb2.RECOVERY,
      key='mp-v2',
  )

  SIGNED_SRC_IRRELEVANT = SignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13421.89.0',
          bucket='b', channel='beta'),
      image_type=common_pb2.TEST,
      key='mp-v2',
  )

  SIGNED_TGT = SignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13425.90.0',
          bucket='b', channel='stable'),
      image_type=common_pb2.RECOVERY,
      key='mp-v2',
  )

  UNSIGNED_SRC = UnsignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13421.89.0',
          bucket='b', channel='stable'),
      milestone='86',
      image_type=common_pb2.TEST,
  )

  UNSIGNED_TGT = UnsignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13425.90.0',
          bucket='b', channel='stable'),
      milestone='86',
      image_type=common_pb2.TEST,
  )

  DLC_SRC = DLCImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13421.89.0',
          bucket='b', channel='stable'),
      dlc_id='termina-dlc',
      dlc_package='package',
      dlc_image='dlc.img',
  )

  DLC_TGT = DLCImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13425.90.0',
          bucket='b', channel='stable'),
      dlc_id='termina-dlc',
      dlc_package='package',
      dlc_image='dlc.img',
  )

  EXAMPLE_GEN_REQUEST_DELTA_SIGNED = [
      GenerationRequest_pb2(
          src_signed_image=SIGNED_SRC,
          tgt_signed_image=SIGNED_TGT,
          bucket='b',
          verify=True,
          keyset='mp-v2',
          dryrun=True,
      )
  ]

  EXAMPLE_GEN_REQUEST_DELTA_UNSIGNED = [
      GenerationRequest_pb2(
          src_unsigned_image=UNSIGNED_SRC,
          tgt_unsigned_image=UNSIGNED_TGT,
          bucket='b',
          verify=True,
          keyset='mp-v2',
          dryrun=True,
      )
  ]

  EXAMPLE_GEN_REQUEST_DELTA_DLC = [
      GenerationRequest_pb2(
          src_dlc_image=DLC_SRC,
          tgt_dlc_image=DLC_TGT,
          bucket='b',
          verify=True,
          keyset='',
          dryrun=True,
      )
  ]

  EXAMPLE_GEN_REQUEST_FULL_SIGNED = [
      GenerationRequest_pb2(
          full_update=True,
          tgt_signed_image=SIGNED_TGT,
          bucket='b',
          verify=True,
          keyset='mp-v2',
          dryrun=True,
      )
  ]

  EXAMPLE_GEN_REQUEST_FULL_UNSIGNED = [
      GenerationRequest_pb2(
          full_update=True,
          tgt_unsigned_image=UNSIGNED_TGT,
          bucket='b',
          verify=True,
          keyset='mp-v2',
          dryrun=True,
      )
  ]

  EXAMPLE_GEN_REQUEST_FULL_DLC = [
      GenerationRequest_pb2(
          full_update=True,
          tgt_dlc_image=DLC_TGT,
          bucket='b',
          verify=True,
          keyset='',
          dryrun=True,
      )
  ]

  EXAMPLE_GEN_REQUEST_N2N = [
      GenerationRequest_pb2(
          src_unsigned_image=UNSIGNED_TGT,
          tgt_unsigned_image=UNSIGNED_TGT,
          bucket='b',
          verify=True,
          keyset='',
          dryrun=True,
      )
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
