# -*- coding: utf-8 -*-

# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.chromiumos.pointless_build import PointlessBuildCheckResponse

from google.protobuf.json_format import MessageToDict
from recipe_engine import recipe_test_api


class CrosRelevanceTestApi(recipe_test_api.RecipeTestApi):
  """Module that aids in testing CrosRelevanceApi."""

  def simulate_run_pointless_build_checker(self, build_is_pointless=False):
    """Mocks running of the pointless build checker binary.

    Args:
      build_is_pointless (bool): whether the build can be terminated early.

    Returns:
      step_data
    """
    resp = PointlessBuildCheckResponse()
    resp.build_is_pointless.value = build_is_pointless
    return self.step_data('pointless build check',
        self.m.json.output(MessageToDict(resp)))
