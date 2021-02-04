# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from recipe_engine import recipe_test_api


class CrosTestRunnerTestApi(recipe_test_api.RecipeTestApi):
  """Test data for cros_test_runner api."""

  def mock_luciexe_call(self, name):
    """Mock CrosTestRunnerCommand invocation.

    Args:
      name: Name the step that calls CrosTestRunnerCommand.execute_luciexe()
    """
    if name != '':
      name += '.'
    name += 'go cros_test_runner'
    return (self.step_data(
        name,
        self.m.step.sub_build(build_pb2.Build(status=common_pb2.SUCCESS))))
