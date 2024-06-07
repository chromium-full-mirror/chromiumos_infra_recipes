# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test API to call into the go luci binary"""

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from recipe_engine import recipe_test_api


class GoLuciBinTestApi(recipe_test_api.RecipeTestApi):
  """Test data for golucibin api."""

  def set_execute_luciexe_response(self, name, package):
    """Set the response from GoLuciBinAPI.execute_luciexe()

        Args:
            name: Name of the step that calls GoLuciBinAPI.execute_luciexe().
            package: Name of the package being called.
            response: A ExecuteResponses payload.
        """
    if name != '':
      name += '.'
    name += '%s sub-build' % package
    return (self.step_data(
        name,
        self.m.step.sub_build(build_pb2.Build(status=common_pb2.SUCCESS))))
