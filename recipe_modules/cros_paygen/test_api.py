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
from PB.chromite.api.payload import GenerationRequest as GenerationRequest_pb2
from PB.chromite.api.payload import SignedImage as SignedImage_pb2
from PB.chromite.api.payload import UnsignedImage as UnsignedImage_pb2
import PB.chromiumos.common as common_pb2
from PB.chromiumos.common import BuildTarget as BuildTarget_pb2


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
          build_target=BuildTarget_pb2(name='coral'), version='12345.6.7',
          bucket='b', channel='stable'),
      image_type=common_pb2.RECOVERY,
      key='mp-v2',
  )

  SIGNED_SRC_IRRELEVANT = SignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='12345.6.7',
          bucket='b', channel='beta'),
      image_type=common_pb2.TEST,
      key='mp-v2',
  )

  SIGNED_TGT = SignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13421.89.0',
          bucket='b', channel='stable'),
      image_type=common_pb2.RECOVERY,
      key='mp-v2',
  )

  UNSIGNED_SRC = UnsignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='12345.6.7',
          bucket='b', channel='stable'),
      milestone='86',
  )

  UNSIGNED_TGT = UnsignedImage_pb2(
      build=Build_pb2(
          build_target=BuildTarget_pb2(name='coral'), version='13421.89.0',
          bucket='b', channel='stable'),
      milestone='86',
  )

  EXAMPLE_GEN_REQUEST_SIGNED = [
      GenerationRequest_pb2(
          src_signed_image=SIGNED_SRC,
          tgt_signed_image=SIGNED_TGT,
          bucket='b',
          verify=True,
          keyset='mp-v2',
          dryrun=True,
      )
  ]
  EXAMPLE_GEN_REQUEST_UNSIGNED = [
      GenerationRequest_pb2(
          src_unsigned_image=UNSIGNED_SRC,
          tgt_unsigned_image=UNSIGNED_TGT,
          bucket='b',
          verify=True,
          keyset='mp-v2',
          dryrun=True,
      )
  ]

  def test_paygen(self, step_name, json_return):
    """Mock up step results for the GS cat."""
    test_response = self.m.step.step_data(
        step_name, stdout=self.m.raw_io.output(json_return))
    return test_response
