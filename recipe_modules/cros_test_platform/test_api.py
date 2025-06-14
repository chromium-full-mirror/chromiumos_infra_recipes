# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from recipe_engine import recipe_test_api


class CrosTestPlatformTestApi(recipe_test_api.RecipeTestApi):
  """Test data for cros_test_platform api."""

  def set_enumerate_response_json(self, name, response):
    """Set the response from CrosTestPlatformCommand.enumerate().

    This method uses serialized JSON to avoid needing to import the chromite
    protobufs.

    Args:
      name: Name the step that calls CrosTestPlatformCommand.enumerate()
      response: A JSON serialized EnumerationResponses payload.
    """
    return self._set_step_data_for_run(name, 'enumerate', response)

  def set_skylab_execute_response(self, name, response):
    """Set the response from CrosTestPlatformCommand.skylab_execute().

    Args:
      name: Name the step that calls CrosTestPlatformCommand.skylab_execute()
      response: A ExecuteResponses payload.
    """
    return self._set_step_data_for_run(name, 'skylab-execute',
                                       json_format.MessageToJson(response))

  def set_execute_luciexe_response(self, name, response):
    """Set the response from CrosTestPlatformCommand.execute_luciexe().

    Args:
      name: Name the step that calls CrosTestPlatformCommand.execute_luciexe()
      response: A ExecuteResponses payload.
    """
    if name != '':
      name += '.'
    name += 'call binary'
    return (self.step_data(
        name + '.launch luciexe',
        self.m.step.sub_build(build_pb2.Build(status=common_pb2.SUCCESS))) +  #
            self.step_data(name + '.read output',
                           self.m.file.read_proto(response)))

  def _set_step_data_for_run(self, name_prefix, subcommand_name, response):
    """Set test data for methods that call CrosTestPlatformCommand._run().

    Args:
      name_prefix: Name of the step that calls the public API method of
          CrosTestPlatformCommand.
      subcommand_name: Name of the step set by the public API method of
          CrosTestPlatformCommand.
      response: A serialized payload for the response from the method.
    """
    name = name_prefix
    if name != '':
      name += '.'
    name += 'call binary.'
    name += subcommand_name
    return self.step_data(name, stdout=self.m.raw_io.output(response))
