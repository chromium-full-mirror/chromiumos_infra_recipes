# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test API to call into the CTPv2 binary"""

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from recipe_engine import recipe_test_api


class Ctpv2TestApi(recipe_test_api.RecipeTestApi):
  """Test data for ctpv2 api."""

  def mock_luciexe_call(self, name):
    """Mock Ctpv2 invocation.

    Args:
      name: Name the step that calls Ctpv2.execute_luciexe()
    """
    if name != '':
      name += '.'
    name += 'ctpv2 sub-build'
    return (self.step_data(
        name,
        self.m.step.sub_build(build_pb2.Build(status=common_pb2.SUCCESS))))
